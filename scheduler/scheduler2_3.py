from __future__ import annotations

from models.context import SchedulerContext
from models.scheduled_class import ScheduledClass
from models.constraints.constraint import Constraint
from models.constraints.subject_constraints import MaxConsecutiveClassesConstraint
from models.constraints.teacher_constraints import UnavailableTimePeriodConstraint
from models.constraints.class_constraints import MaxDailyClassCount, MinDailyClassCount
import math
import time

NON_COMPACT_GRADES = {0, 1, 2, 3, 4}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# Sentinel: backjump target class index, carried up the call stack
_BACKJUMP = object()


class Scheduler:
    def __init__(self, context: SchedulerContext):
        self.context = context
        self._hard_constraints, self._soft_constraints = self._collect_constraints()

    # ── Public API ─────────────────────────────────────────────────────────────

    def solve(self) -> bool:
        self._cancel_event = None
        success = self._solve_compact()
        if not success:
            self._clear_all()
        return success

    def solve_top_n(self, max_solutions: int = 10, cancel_event=None) -> bool:
        self._cancel_event = cancel_event
        self._max_solutions = max_solutions
        self._solutions_found = 0
        self._best_score = -1
        self._best_slots: dict = {}
        self._solve_compact(collect_best=True)
        if self._best_slots:
            self._restore_best()
            return True
        self._clear_all()
        return False

    def solve_best(self, time_limit: float = 30.0, cancel_event=None) -> bool:
        self._deadline = time.monotonic() + time_limit
        self._best_score = -1
        self._best_slots: dict = {}
        self._cancel_event = cancel_event
        self._solve_compact(collect_best=True, use_deadline=True)
        if self._best_slots:
            self._restore_best()
            return True
        self._clear_all()
        return False

    def solve_portfolio(self, time_limit: float = 120.0) -> bool:
        import random

        orderings = self._build_portfolio_orderings()
        n_fixed = len(orderings)

        fixed_weights = [0.35, 0.25, 0.20, 0.15][:n_fixed]
        total_fw      = sum(fixed_weights)
        fixed_budgets = [time_limit * w / total_fw * 0.95 for w in fixed_weights]
        restart_budget = time_limit * 0.05
        restart_each   = max(4.0, restart_budget / 4)

        last_conflict_cls      = None
        last_conflict_teachers = set()
        deadline_global        = time.monotonic() + time_limit

        for attempt_idx, ordering in enumerate(orderings):

            if last_conflict_cls is not None and attempt_idx > 0:
                cluster = self._contention_cluster(ordering, last_conflict_cls, last_conflict_teachers)
                ordering = self._promote_cluster(ordering, cluster)

            budget = fixed_budgets[attempt_idx]
            print(
                f"\n[Portfolio] ── Attempt {attempt_idx + 1}/{n_fixed} "
                f"(budget={budget:.1f}s) ──────────────────────────"
            )
            print(f"[Portfolio] Order: {[f'{c.grade}{c.version}' for c in ordering]}")

            self._clear_all()
            self._deadline          = time.monotonic() + budget
            self._conflict_cls      = None
            self._conflict_teachers = set()

            success = self._solve_compact(
                collect_best=False,
                use_deadline=True,
                forced_ordering=ordering,
            )

            if success:
                print(f"\n[Portfolio] ✓ Solution found on attempt {attempt_idx + 1}")
                return True

            last_conflict_cls      = self._conflict_cls
            last_conflict_teachers = getattr(self, "_conflict_teachers", set())
            if last_conflict_cls:
                print(
                    f"[Portfolio] ✗ Failed — conflict class: "
                    f"{last_conflict_cls.grade}{last_conflict_cls.version}, "
                    f"contention teachers: {list(last_conflict_teachers)}"
                )
            else:
                print("[Portfolio] ✗ Failed — no conflict class detected")

        # random-restart sweep with remaining time
        base_order = list(self.context.classes)
        restart_num = 0
        rng = random.Random(42)

        while time.monotonic() < deadline_global - 1.0:
            restart_num += 1
            shuffled = list(base_order)
            rng.shuffle(shuffled)

            if last_conflict_cls is not None:
                cluster  = self._contention_cluster(shuffled, last_conflict_cls, last_conflict_teachers)
                shuffled = self._promote_cluster(shuffled, cluster)

            budget = min(restart_each, deadline_global - time.monotonic() - 0.5)
            if budget < 1.0:
                break

            print(
                f"\n[Portfolio] ── Random restart {restart_num} "
                f"(budget={budget:.1f}s) ──────────────────────────"
            )

            self._clear_all()
            self._deadline          = time.monotonic() + budget
            self._conflict_cls      = None
            self._conflict_teachers = set()

            success = self._solve_compact(
                collect_best=False,
                use_deadline=True,
                forced_ordering=shuffled,
            )

            if success:
                print(f"\n[Portfolio] ✓ Solution found on random restart {restart_num}")
                return True

            last_conflict_cls      = self._conflict_cls
            last_conflict_teachers = getattr(self, "_conflict_teachers", set())

        print("\n[Portfolio] All attempts exhausted — no solution found.")
        self._clear_all()
        return False

    # ── Portfolio helpers ──────────────────────────────────────────────────────

    def _compute_priority_order(self, classes: list, teacher_unavailable: dict | None = None) -> list:
        teacher_remaining: dict[int, int] = {}
        teacher_reqs: dict[int, list] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid not in teacher_reqs:
                    teacher_reqs[tid]     = []
                    teacher_remaining[tid] = 0
                teacher_reqs[tid].append((id(cls), req))
                teacher_remaining[tid] += req.sessions_per_week

        if teacher_unavailable is None:
            teacher_unavailable = {}
            for cls in classes:
                for req in cls.subject_requirements:
                    tid = id(req.teacher)
                    if tid not in teacher_unavailable:
                        unavail = set()
                        for c in req.teacher.constraints:
                            if isinstance(c, UnavailableTimePeriodConstraint):
                                unavail = c._unavailable_set
                                break
                        teacher_unavailable[tid] = unavail

        teacher_free: dict[int, set] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid not in teacher_free:
                    unavail = teacher_unavailable.get(tid, set())
                    teacher_free[tid] = {
                        (d, h)
                        for d in range(5) for h in range(8)
                        if req.teacher.schedule.is_free(d, h)
                        and (d, h) not in unavail
                    }

        def class_priority(cls):
            worst = 0.0
            shared = 0.0
            for req in cls.subject_requirements:
                tid       = id(req.teacher)
                available = len(teacher_free[tid])
                total_load = teacher_remaining[tid]
                competing = len(set(cid for cid, _ in teacher_reqs.get(tid, [])))
                util      = total_load / max(available, 1)
                pressure  = util * req.sessions_per_week * competing
                worst     = max(worst, pressure)
                shared   += util
            return worst + 0.1 * shared

        return sorted(classes, key=class_priority, reverse=True)

    def _build_portfolio_orderings(self) -> list[list]:
        classes = list(self.context.classes)

        teacher_unavailable: dict[int, set] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid not in teacher_unavailable:
                    unavail = set()
                    for c in req.teacher.constraints:
                        if isinstance(c, UnavailableTimePeriodConstraint):
                            unavail = c._unavailable_set
                            break
                    teacher_unavailable[tid] = unavail

        teacher_free: dict[int, set] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid not in teacher_free:
                    unavail = teacher_unavailable.get(tid, set())
                    teacher_free[tid] = {
                        (d, h)
                        for d in range(5) for h in range(8)
                        if req.teacher.schedule.is_free(d, h)
                        and (d, h) not in unavail
                    }

        teacher_remaining: dict[int, int] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                teacher_remaining[tid] = teacher_remaining.get(tid, 0) + req.sessions_per_week

        o1 = self._compute_priority_order(classes, teacher_unavailable)

        def utilisation_key(cls):
            ratios = []
            for req in cls.subject_requirements:
                tid   = id(req.teacher)
                free  = len(teacher_free[tid])
                load  = teacher_remaining[tid]
                ratios.append(load / max(free, 1))
            return max(ratios) if ratios else 0.0

        o2 = sorted(classes, key=utilisation_key, reverse=True)

        def volume_scarcity_key(cls):
            total = sum(r.sessions_per_week for r in cls.subject_requirements)
            scarcity = sum(
                r.sessions_per_week / max(len(teacher_free[id(r.teacher)]), 1)
                for r in cls.subject_requirements
            )
            return total * scarcity

        o3 = sorted(classes, key=volume_scarcity_key, reverse=True)

        o4 = sorted(
            o1,
            key=lambda c: (1 if c.grade not in NON_COMPACT_GRADES else 0),
        )

        orderings = [o1, o2, o3, o4]
        print("\n[Portfolio] Built orderings:")
        for i, o in enumerate(orderings):
            print(f"  [{i+1}] {[f'{c.grade}{c.version}' for c in o]}")
        return orderings

    def _contention_cluster(self, ordering, conflict_cls, conflict_teachers) -> list:
        if not conflict_teachers:
            conflict_tids = {id(req.teacher) for req in conflict_cls.subject_requirements}
        else:
            conflict_tids = {id(t) for t in conflict_teachers}

        cluster = [conflict_cls]
        for cls in ordering:
            if cls is conflict_cls:
                continue
            cls_tids = {id(req.teacher) for req in cls.subject_requirements}
            if cls_tids & conflict_tids:
                cluster.append(cls)
        return cluster

    def _promote_cluster(self, ordering: list, cluster: list) -> list:
        cluster_set = {id(c) for c in cluster}
        rest = [c for c in ordering if id(c) not in cluster_set]
        return list(cluster) + rest

    def _promote_conflict(self, ordering: list, conflict_cls) -> list:
        result = [c for c in ordering if c is not conflict_cls]
        return [conflict_cls] + result

    # ── Core solver ────────────────────────────────────────────────────────────

    def _solve_compact(
        self,
        collect_best: bool = False,
        use_deadline: bool = False,
        forced_ordering: list | None = None,
    ) -> bool:

        if forced_ordering is not None:
            classes = list(forced_ordering)
        else:
            classes = sorted(
                self.context.classes,
                key=lambda c: sum(r.sessions_per_week for r in c.subject_requirements),
                reverse=True,
            )

        n_classes = len(classes)

        # Pre-cache unavailable sets per teacher
        teacher_unavailable: dict[int, set[tuple[int, int]]] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid not in teacher_unavailable:
                    unavail = set()
                    for c in req.teacher.constraints:
                        if isinstance(c, UnavailableTimePeriodConstraint):
                            unavail = c._unavailable_set
                            break
                    teacher_unavailable[tid] = unavail

        # Build teacher_reqs and teacher_remaining
        teacher_reqs: dict[int, list[tuple[int, int]]] = {}
        teacher_remaining: dict[int, int] = {}
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                tid = id(req.teacher)
                if tid not in teacher_reqs:
                    teacher_reqs[tid] = []
                    teacher_remaining[tid] = 0
                teacher_reqs[tid].append((ci, ri))
                teacher_remaining[tid] += req.sessions_per_week

        # Build teacher_free
        teacher_free: dict[int, set[tuple[int, int]]] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid not in teacher_free:
                    unavail = teacher_unavailable.get(tid, set())
                    teacher_free[tid] = {
                        (d, h)
                        for d in range(5) for h in range(8)
                        if req.teacher.schedule.is_free(d, h)
                        and (d, h) not in unavail
                    }

        # Only apply internal priority sort when no forced ordering was supplied
        if forced_ordering is None:
            def class_priority(cls):
                worst = 0.0
                shared_pressure = 0.0
                for req in cls.subject_requirements:
                    tid = id(req.teacher)
                    available = len(teacher_free[tid])
                    total_load = teacher_remaining[tid]
                    competing_classes = len(set(ci for ci, ri in teacher_reqs.get(tid, [])))
                    utilization = total_load / max(available, 1)
                    pressure = utilization * req.sessions_per_week * competing_classes
                    worst = max(worst, pressure)
                    shared_pressure += utilization
                return worst + 0.1 * shared_pressure

            classes = sorted(classes, key=class_priority, reverse=True)

        # Rebuild all index-dependent structures after (possible) re-sort
        compact_flag   = [cls.grade not in NON_COMPACT_GRADES for cls in classes]
        remaining      = [
            {i: req.sessions_per_week for i, req in enumerate(cls.subject_requirements)}
            for cls in classes
        ]
        max_consec_map = [self._get_max_consecutive(cls) for cls in classes]

        max_daily_cap   = []
        min_daily_floor = []
        for cls in classes:
            cap   = 8
            floor = 0
            for c in cls.constraints:
                if isinstance(c, MaxDailyClassCount):
                    cap = min(cap, c.max_classes)
                if isinstance(c, MinDailyClassCount):
                    floor = max(floor, c.min_classes)
            max_daily_cap.append(cap)
            min_daily_floor.append(floor)

        teacher_reqs      = {}
        teacher_remaining = {}
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                tid = id(req.teacher)
                if tid not in teacher_reqs:
                    teacher_reqs[tid] = []
                    teacher_remaining[tid] = 0
                teacher_reqs[tid].append((ci, ri))
                teacher_remaining[tid] += req.sessions_per_week

        # ── FIX B: Cross-class teacher slot reservation ────────────────────────
        # For each teacher, pre-partition their available slots across the classes
        # that need them.  We record, for each (teacher, class), a *reserved* set
        # of slots that only that class may use for that teacher.  The reservation
        # is rebuilt whenever we backtrack past a class boundary.
        #
        # We do NOT enforce the reservation as a hard constraint inside the
        # backtracker; instead we use it as a forward-checking signal:
        # _can_complete_teacher_cross_class() checks that each pending class that
        # shares a teacher still has at least as many usable slots as it needs,
        # accounting for the fact that slots used by an earlier class are gone.
        #
        # This replaces the weak global "teacher_free >= teacher_remaining" check
        # with a per-class feasibility proof.

        # teacher_class_needs[tid] = list of (ci, sessions_needed) sorted by
        # scheduling order (ci ascending = earlier in ordering = higher priority).
        teacher_class_needs: dict[int, list[tuple[int, int]]] = {}
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                tid = id(req.teacher)
                if tid not in teacher_class_needs:
                    teacher_class_needs[tid] = []
                teacher_class_needs[tid].append((ci, req.sessions_per_week))

        def _build_valid_slots() -> list[list[set]]:
            vs: list[list[set]] = []
            for ci, cls in enumerate(classes):
                row: list[set] = []
                for ri, req in enumerate(cls.subject_requirements):
                    unavail = teacher_unavailable.get(id(req.teacher), set())
                    s = set()
                    for d in range(5):
                        for h in range(8):
                            if (
                                cls.schedule.is_free(d, h)
                                and req.teacher.schedule.is_free(d, h)
                                and (d, h) not in unavail
                            ):
                                s.add((d, h))
                    row.append(s)
                vs.append(row)
            return vs

        valid_slots = _build_valid_slots()

        # Rebuild teacher_free after re-sort
        teacher_free = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid not in teacher_free:
                    unavail = teacher_unavailable.get(tid, set())
                    teacher_free[tid] = {
                        (d, h)
                        for d in range(5) for h in range(8)
                        if req.teacher.schedule.is_free(d, h)
                        and (d, h) not in unavail
                    }

        _nogood_cache: set[tuple] = set()

        def _rem_sig(cls_idx: int) -> tuple:
            return tuple(
                (ri, cnt, len(valid_slots[cls_idx][ri]))
                for ri, cnt in sorted(remaining[cls_idx].items())
                if cnt > 0
            )

        call_count  = [0]
        last_report = [time.monotonic()]
        deepest     = [(0, 0)]
        start_time  = time.monotonic()
        deepest_completed_cls = [-1]

        # ── FIX A: Conflict-directed backjumping state ─────────────────────────
        # When a failure is detected, we record the *culprit class index* —
        # the earliest class (lowest ci) whose assignment decisions caused the
        # conflict.  The backtracker returns the sentinel _BACKJUMP paired with
        # this index instead of False, and every intermediate frame propagates
        # it upward until the matching class index is reached, at which point
        # normal backtracking resumes (trying the next value for that class).
        #
        # culprit_cls[0] holds the current backjump target (-1 = no jump active).
        culprit_cls = [-1]

        def clabel(idx: int) -> str:
            if idx >= n_classes:
                return "DONE"
            c = classes[idx]
            return f"{c.grade}{c.version}"

        def report(cls_idx: int, day: int, tag: str = ""):
            now = time.monotonic()
            if now - last_report[0] < 3.0:
                return
            last_report[0] = now
            dc, dd = deepest[0]
            print(
                f"[{now - start_time:6.1f}s] calls={call_count[0]:,}  "
                f"cur=cls{clabel(cls_idx)}/{DAY_NAMES[day] if day < 5 else '?'}  "
                f"deepest=cls{clabel(dc)}/{DAY_NAMES[dd] if dd < 5 else '?'}"
                + (f"  {tag}" if tag else "")
                + f"  nogoods={len(_nogood_cache):,}"
            )
            for ci in range(cls_idx, min(cls_idx + 4, n_classes)):
                rem_str = {
                    classes[ci].subject_requirements[ri].subject.name: cnt
                    for ri, cnt in remaining[ci].items() if cnt > 0
                }
                flag = "COMPACT" if compact_flag[ci] else "free"
                print(f"         cls{clabel(ci)} [{flag}] remaining={rem_str}")
            busy = {
                t.name: sum(1 for v in t.schedule.slots.values() if v is not None)
                for t in self.context.teachers
                if any(v is not None for v in t.schedule.slots.values())
            }
            if busy:
                print(f"         teacher load: {busy}")

        # ── Incremental assign/unassign ────────────────────────────────────────

        def _assign_and_update(cls_idx, cls, req, req_idx, rem, day, hour):
            sc = ScheduledClass(
                school_class=cls,
                subject=req.subject,
                teacher=req.teacher,
                room=req.room,
                day=day,
                hour=hour,
            )
            cls.schedule.assign(day, hour, sc)
            req.teacher.schedule.assign(day, hour, sc)
            req.room.schedule.assign(day, hour, sc)
            rem[req_idx] -= 1
            teacher_remaining[id(req.teacher)] -= 1

            slot = (day, hour)
            tid  = id(req.teacher)

            teacher_free[tid].discard(slot)

            for ri2 in range(len(classes[cls_idx].subject_requirements)):
                valid_slots[cls_idx][ri2].discard(slot)

            for ci2, ri2 in teacher_reqs.get(tid, []):
                if ci2 != cls_idx:
                    valid_slots[ci2][ri2].discard(slot)

        def _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour):
            cls.schedule.clear(day, hour)
            req.teacher.schedule.clear(day, hour)
            req.room.schedule.clear(day, hour)
            rem[req_idx] += 1
            teacher_remaining[id(req.teacher)] += 1

            slot    = (day, hour)
            tid     = id(req.teacher)
            unavail = teacher_unavailable.get(tid, set())

            if slot not in unavail:
                teacher_free[tid].add(slot)

            for ri2, req2 in enumerate(classes[cls_idx].subject_requirements):
                tid2     = id(req2.teacher)
                unavail2 = teacher_unavailable.get(tid2, set())
                if (
                    slot not in unavail2
                    and req2.teacher.schedule.is_free(day, hour)
                ):
                    valid_slots[cls_idx][ri2].add(slot)

            if slot not in unavail:
                for ci2, ri2 in teacher_reqs.get(tid, []):
                    if ci2 != cls_idx:
                        cls2 = classes[ci2]
                        if cls2.schedule.is_free(day, hour):
                            valid_slots[ci2][ri2].add(slot)

        # ── Forward-checking helpers ───────────────────────────────────────────

        def _can_complete_current_class(cls_idx: int, days_left: int, today_count: int = 0) -> bool:
            rem   = remaining[cls_idx]
            cap   = max_daily_cap[cls_idx]
            floor = min_daily_floor[cls_idx]

            total_rem = sum(rem.values())

            if total_rem > days_left * cap:
                return False

            if floor > 0 and total_rem > 0:
                if today_count > 0:
                    today_still_needed = max(0, floor - today_count)
                    if today_still_needed > total_rem:
                        return False
                    future_rem = total_rem - today_still_needed
                    future_days = days_left - 1
                    if future_rem > 0 and future_days >= 0:
                        if future_rem > future_days * cap:
                            return False
                        min_future_days = math.ceil(future_rem / cap)
                        if min_future_days * floor > future_rem:
                            return False
                else:
                    min_days_needed = math.ceil(total_rem / cap)
                    if min_days_needed * floor > total_rem:
                        return False

            for ri, count in rem.items():
                if count == 0:
                    continue

                slots = valid_slots[cls_idx][ri]

                if len(slots) < count:
                    return False

                req = classes[cls_idx].subject_requirements[ri]
                max_consec = max_consec_map[cls_idx].get(req.subject.name, 30)

                if max_consec == 1:
                    days_with_slots = len({d for (d, h) in slots})
                    if days_with_slots < count:
                        return False

                tid = id(req.teacher)
                if len(teacher_free[tid]) < teacher_remaining[tid]:
                    return False

            return True

        # ── FIX B: Cross-class teacher feasibility check ───────────────────────
        # For each teacher that cls_idx shares with future classes, verify that
        # the teacher's remaining free slots can satisfy ALL pending classes —
        # not just the global total.
        #
        # Method: for each (teacher, future class) pair, count how many of the
        # teacher's current free slots are also valid for that class (i.e. the
        # class itself is also free at that slot).  If any future class has fewer
        # such slots than sessions still needed, we have a proven failure.
        #
        # This is O(teachers_in_class × future_classes_sharing_teacher × free_slots)
        # but the constants are small in practice.
        #
        # Additionally, we identify the *earliest* future class that would be
        # made infeasible, and set culprit_cls to that class index so the
        # backjumper can skip past the irrelevant intermediate classes.

        def _can_complete_teacher_cross_class(cls_idx: int) -> bool:
            """
            For every teacher used by cls_idx, check that each future class
            sharing that teacher still has enough valid slots after the current
            assignment.  Sets culprit_cls[0] to the earliest infeasible class
            to enable backjumping.
            """
            for ri, req in enumerate(classes[cls_idx].subject_requirements):
                tid = id(req.teacher)
                free_slots = teacher_free[tid]  # already updated by _assign_and_update

                for ci2, ri2 in teacher_reqs.get(tid, []):
                    if ci2 <= cls_idx:
                        continue  # already scheduled
                    needed = remaining[ci2][ri2]
                    if needed == 0:
                        continue

                    # Count teacher slots that are valid for ci2 as well
                    usable = valid_slots[ci2][ri2]  # maintained incrementally
                    if len(usable) < needed:
                        # Failure: identify the culprit as the earliest class
                        # that shares this teacher and is still unscheduled.
                        # That is ci2 itself (or earlier if another req also fails).
                        if culprit_cls[0] == -1 or ci2 < culprit_cls[0]:
                            culprit_cls[0] = ci2
                        return False

                    # max_consec == 1 check: need sessions on distinct days
                    req2 = classes[ci2].subject_requirements[ri2]
                    mc2 = max_consec_map[ci2].get(req2.subject.name, 30)
                    if mc2 == 1:
                        days_with_slots = len({d for (d, h) in usable})
                        if days_with_slots < needed:
                            if culprit_cls[0] == -1 or ci2 < culprit_cls[0]:
                                culprit_cls[0] = ci2
                            return False

            return True

        def _can_complete_teacher(teacher) -> bool:
            tid    = id(teacher)
            needed = teacher_remaining.get(tid, 0)
            if needed == 0:
                return True
            if len(teacher_free[tid]) < needed:
                return False
            for ci, ri in teacher_reqs.get(tid, []):
                count = remaining[ci][ri]
                if count == 0:
                    continue
                if len(valid_slots[ci][ri]) < count:
                    return False
                req = classes[ci].subject_requirements[ri]
                mc = max_consec_map[ci].get(req.subject.name, 30)
                if mc == 1:
                    days_with_slots = len({d for (d, h) in valid_slots[ci][ri]})
                    if days_with_slots < count:
                        return False
            return True

        # ── FIX A: Backjump-aware result helpers ───────────────────────────────
        #
        # Backtrackers return:
        #   True          → solution found (propagate up normally)
        #   False         → failure at this level (try next value)
        #   _BACKJUMP     → jump: skip straight to culprit_cls[0], don't try
        #                   other values at intermediate levels
        #
        # Each backtracking frame checks: if the result is _BACKJUMP and
        # culprit_cls[0] < my cls_idx, propagate _BACKJUMP up.
        # If culprit_cls[0] == my cls_idx, reset culprit_cls[0] = -1 and
        # resume normal backtracking (try remaining values).

        def _should_propagate_jump(cls_idx: int) -> bool:
            """True if we should propagate the backjump past this frame."""
            return culprit_cls[0] != -1 and culprit_cls[0] < cls_idx

        # ── compact backtracker (grades 5+) ────────────────────────────────────

        def backtrack_compact(cls_idx: int, day: int, hour: int):
            call_count[0] += 1
            if (cls_idx, day) > deepest[0]:
                deepest[0] = (cls_idx, day)
            if call_count[0] % 100_000 == 0:
                report(cls_idx, day)
            if use_deadline and time.monotonic() > self._deadline:
                print("[DEBUG] deadline reached")
                return False

            if self._cancel_event is not None and self._cancel_event.is_set():
                print("[DEBUG] cancelled by client")
                return False

            if cls_idx == n_classes:
                return _record_solution()

            cls   = classes[cls_idx]
            rem   = remaining[cls_idx]
            total_rem = sum(rem.values())
            cap   = max_daily_cap[cls_idx]
            floor = min_daily_floor[cls_idx]

            if total_rem == 0:
                if hour > 0 and floor > 0 and hour < floor:
                    return False
                print(
                    f"[DEBUG] cls{clabel(cls_idx)} done after {call_count[0]:,} calls"
                    f" → next: cls{clabel(cls_idx + 1)}"
                )
                if cls_idx > deepest_completed_cls[0]:
                    deepest_completed_cls[0] = cls_idx
                result = _dispatch(cls_idx + 1, 0, 0)
                # FIX A: if backjump targets this class or earlier, let it
                # propagate; otherwise return normally
                if result is _BACKJUMP and not _should_propagate_jump(cls_idx):
                    # The jump targets this class — but we have no more values
                    # to try here (sessions already placed).  Reset and fail.
                    culprit_cls[0] = -1
                    return False
                return result

            if day >= 5:
                return False

            days_left = 5 - day

            if total_rem > days_left * cap:
                return False
            
            ng_key = (cls_idx, day, hour, _rem_sig(cls_idx))
            if ng_key in _nogood_cache:
                return False

            days_after  = 5 - (day + 1)
            can_end_today = (total_rem <= days_after * cap)

            today_count = hour
            if hour > 0 and floor > 0 and today_count < floor:
                can_end_today = False

            # ── Option A: place a session at (day, hour) ──────────────────────
            placed_any = False
            if hour < 8 and hour < cap:
                active_reqs = [
                    (ri, cls.subject_requirements[ri])
                    for ri, cnt in rem.items()
                    if cnt > 0
                ]
                active_reqs.sort(key=lambda t: len(valid_slots[cls_idx][t[0]]))

                for req_idx, req in active_reqs:
                    if (day, hour) not in valid_slots[cls_idx][req_idx]:
                        continue

                    teacher, room = req.teacher, req.room
                    max_consec = max_consec_map[cls_idx].get(req.subject.name, 30)

                    if not self._check_consecutive(cls, req.subject, day, hour, max_consec):
                        continue

                    if not room.schedule.is_free(day, hour):
                        continue

                    placed_any = True
                    culprit_cls[0] = -1  # reset before descending
                    _assign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

                    feasible = (
                        self._check_hard(cls, teacher, room)
                        and _can_complete_current_class(cls_idx, days_left, today_count=hour + 1)
                        and _can_complete_teacher(teacher)
                        # FIX B: cross-class check (also sets culprit_cls on failure)
                        and _can_complete_teacher_cross_class(cls_idx)
                    )

                    if feasible:
                        result = backtrack_compact(cls_idx, day, hour + 1)
                        if result is True:
                            return True
                        if result is _BACKJUMP:
                            _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)
                            if _should_propagate_jump(cls_idx):
                                return _BACKJUMP
                            # Jump targets this class — resume trying other values
                            culprit_cls[0] = -1
                            # continue to next req_idx / Option B
                    else:
                        # FIX A: if cross-class check set a culprit earlier than
                        # this class, propagate the jump immediately
                        if culprit_cls[0] != -1 and culprit_cls[0] < cls_idx:
                            _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)
                            return _BACKJUMP

                    _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

            # ── Option B: end this day's block ────────────────────────────────
            if can_end_today:
                culprit_cls[0] = -1
                result = backtrack_compact(cls_idx, day + 1, 0)
                if result is True:
                    return True
                if result is _BACKJUMP:
                    if _should_propagate_jump(cls_idx):
                        return _BACKJUMP
                    culprit_cls[0] = -1

            _nogood_cache.add(ng_key)
            return False

        # ── free backtracker (grades 0-4) ──────────────────────────────────────

        def backtrack_free(cls_idx: int):
            call_count[0] += 1
            if call_count[0] % 100_000 == 0:
                report(cls_idx, 0, tag="[free-mode]")

            if use_deadline and time.monotonic() > self._deadline:
                print("[DEBUG] deadline reached")
                return False

            if self._cancel_event is not None and self._cancel_event.is_set():
                print("[DEBUG] cancelled by client")
                return False

            if cls_idx == n_classes:
                return _record_solution()

            cls = classes[cls_idx]
            rem = remaining[cls_idx]
            total_rem = sum(rem.values())

            if total_rem == 0:
                print(
                    f"[DEBUG] cls{clabel(cls_idx)} done after {call_count[0]:,} calls"
                    f" → next: cls{clabel(cls_idx + 1)}"
                )
                if cls_idx > deepest_completed_cls[0]:
                    deepest_completed_cls[0] = cls_idx
                result = _dispatch(cls_idx + 1, 0, 0)
                if result is _BACKJUMP and not _should_propagate_jump(cls_idx):
                    culprit_cls[0] = -1
                    return False
                return result

            active_reqs = [
                (ri, cls.subject_requirements[ri])
                for ri, cnt in rem.items()
                if cnt > 0
            ]
            active_reqs.sort(key=lambda t: len(valid_slots[cls_idx][t[0]]))

            for req_idx, req in active_reqs:
                teacher, room = req.teacher, req.room
                max_consec = max_consec_map[cls_idx].get(req.subject.name, 30)

                for (day, hour) in sorted(valid_slots[cls_idx][req_idx]):
                    if not self._check_consecutive(cls, req.subject, day, hour, max_consec):
                        continue
                    if not room.schedule.is_free(day, hour):
                        continue

                    culprit_cls[0] = -1
                    _assign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

                    feasible = (
                        self._check_hard(cls, teacher, room)
                        and _can_complete_current_class(cls_idx, 5)
                        and _can_complete_teacher(teacher)
                        and _can_complete_teacher_cross_class(cls_idx)
                    )

                    if feasible:
                        result = backtrack_free(cls_idx)
                        if result is True:
                            return True
                        if result is _BACKJUMP:
                            _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)
                            if _should_propagate_jump(cls_idx):
                                return _BACKJUMP
                            culprit_cls[0] = -1
                    else:
                        if culprit_cls[0] != -1 and culprit_cls[0] < cls_idx:
                            _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)
                            return _BACKJUMP

                    _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

                return False

            return _dispatch(cls_idx + 1, 0, 0)

        # ── shared helpers ─────────────────────────────────────────────────────

        def _dispatch(cls_idx: int, day: int, hour: int):
            if cls_idx >= n_classes:
                return _record_solution()

            for ri, req in enumerate(classes[cls_idx].subject_requirements):
                if remaining[cls_idx][ri] == 0:
                    continue
                if not _can_complete_teacher(req.teacher):
                    if self._conflict_cls is None:
                        self._conflict_cls = classes[cls_idx]
                        if not hasattr(self, "_conflict_teachers"):
                            self._conflict_teachers = set()
                        self._conflict_teachers.add(req.teacher)
                    return False

            if compact_flag[cls_idx]:
                return backtrack_compact(cls_idx, day, hour)
            else:
                return backtrack_free(cls_idx)

        def _record_solution():
            if collect_best:
                score = self._total_soft_score()
                if score > self._best_score:
                    self._best_score = score
                    self._best_slots = self._snapshot()
                self._solutions_found = getattr(self, "_solutions_found", 0) + 1
                max_sol = getattr(self, "_max_solutions", 1)
                print(
                    f"[DEBUG] solution #{self._solutions_found} score={score}"
                    f" after {call_count[0]:,} calls"
                )
                return self._solutions_found >= max_sol
            print(f"[DEBUG] solution found after {call_count[0]:,} calls")
            return True

        # ── pre-solve checks ───────────────────────────────────────────────────
        print(f"[DEBUG] Solver start — {n_classes} classes, {len(self.context.teachers)} teachers")
        for ci, cls in enumerate(classes):
            total = sum(r.sessions_per_week for r in cls.subject_requirements)
            reqs  = {f"{r.subject.name}({r.teacher.name})": r.sessions_per_week for r in cls.subject_requirements}
            flag  = "COMPACT" if compact_flag[ci] else "free"
            consec = max_consec_map[ci]
            print(f"  cls{clabel(ci)} [{flag}] {total} sessions  cap={max_daily_cap[ci]} floor={min_daily_floor[ci]} — {reqs}"
                  + (f" max_consec={consec}" if consec else ""))

        print("\n[DEBUG] Pre-solve teacher capacity check:")
        infeasible = False
        for teacher in self.context.teachers:
            tid = id(teacher)
            unavail = teacher_unavailable.get(tid, set())
            total_available = sum(
                1
                for d in range(5)
                for h in range(8)
                if (d, h) not in unavail
            )
            refs = teacher_reqs.get(tid, [])
            total_needed = sum(remaining[ci][ri] for ci, ri in refs)
            if total_needed == 0:
                continue
            status = "OK" if total_available >= total_needed else "*** INFEASIBLE ***"
            if total_available < total_needed:
                infeasible = True
            print(f"  {teacher.name}: needs={total_needed} available={total_available} {status}")
        if infeasible:
            print("[DEBUG] Pre-solve check FAILED — problem is unsolvable as configured.")
            return False
        print("[DEBUG] Pre-solve check passed.\n")

        print("[DEBUG] Pre-solve cap feasibility check:")
        cap_infeasible = False
        for ci, cls in enumerate(classes):
            total = sum(remaining[ci].values())
            cap   = max_daily_cap[ci]
            floor = min_daily_floor[ci]
            if total > 5 * cap:
                print(
                    f"  *** INFEASIBLE *** cls{clabel(ci)}: needs={total} but "
                    f"5 days × cap={cap} = {5 * cap}"
                )
                cap_infeasible = True
            if floor > 0 and total > 0:
                min_days = math.ceil(total / cap)
                if min_days * floor > total:
                    print(
                        f"  *** INFEASIBLE *** cls{clabel(ci)}: needs={total} sessions, "
                        f"min {min_days} days × floor={floor} = {min_days * floor} > {total}. "
                        f"Raise MaxDailyClassCount or lower MinDailyClassCount."
                    )
                    cap_infeasible = True
        if cap_infeasible:
            print("[DEBUG] Cap feasibility check FAILED.")
            return False
        print("[DEBUG] Cap feasibility check passed.\n")

        print("[DEBUG] Pre-solve per-req days-available check:")
        days_infeasible = False
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                count = remaining[ci][ri]
                mc    = max_consec_map[ci].get(req.subject.name, 30)
                if mc == 1:
                    days_with_slots = len({d for (d, h) in valid_slots[ci][ri]})
                    if days_with_slots < count:
                        print(
                            f"  *** INFEASIBLE *** cls{clabel(ci)} "
                            f"{req.subject.name}({req.teacher.name}): "
                            f"needs={count} sessions on distinct days but "
                            f"only {days_with_slots} days have valid slots"
                        )
                        days_infeasible = True
        if days_infeasible:
            print("[DEBUG] Days-available check FAILED.")
            return False
        print("[DEBUG] Days-available check passed.\n")

        print("[DEBUG] Valid slot counts for most constrained requirements:")
        bottlenecks = []
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                needed = remaining[ci][ri]
                avail  = len(valid_slots[ci][ri])
                ratio  = avail / max(needed, 1)
                bottlenecks.append((ratio, ci, ri, cls, req, needed, avail))
        bottlenecks.sort()
        for ratio, ci, ri, cls, req, needed, avail in bottlenecks[:10]:
            print(
                f"  cls{clabel(ci)} {req.subject.name}({req.teacher.name}): "
                f"needs={needed} valid_slots={avail} ratio={ratio:.1f}"
            )
        print()

        # ── FIX B: Pre-solve cross-class teacher distribution check ────────────
        # Verify that for each teacher, their available slots can be distributed
        # across all classes that need them simultaneously — not just in total.
        # This catches cases that pass the global capacity check but are still
        # infeasible due to class schedule conflicts with a shared teacher.
        print("[DEBUG] Pre-solve cross-class teacher distribution check:")
        cross_infeasible = False
        for teacher in self.context.teachers:
            tid = id(teacher)
            refs = teacher_reqs.get(tid, [])
            if not refs:
                continue

            # For each class that needs this teacher, count how many of the
            # teacher's globally free slots are also free for that class.
            for ci, ri in refs:
                needed = remaining[ci][ri]
                if needed == 0:
                    continue
                usable = len(valid_slots[ci][ri])
                if usable < needed:
                    print(
                        f"  *** INFEASIBLE *** cls{clabel(ci)} "
                        f"{classes[ci].subject_requirements[ri].subject.name}"
                        f"({teacher.name}): needs={needed} but only "
                        f"{usable} slots are free for both teacher and class"
                    )
                    cross_infeasible = True
        if cross_infeasible:
            print("[DEBUG] Cross-class distribution check FAILED.")
            return False
        print("[DEBUG] Cross-class distribution check passed.\n")

        # Initialise conflict tracker
        if not hasattr(self, "_conflict_cls"):
            self._conflict_cls = None

        result = _dispatch(0, 0, 0)
        elapsed = time.monotonic() - start_time

        # Normalise: _BACKJUMP at the top level means failure
        if result is _BACKJUMP:
            result = False

        if not result and self._conflict_cls is None:
            next_idx = deepest_completed_cls[0] + 1
            if 0 <= next_idx < n_classes:
                self._conflict_cls = classes[next_idx]
                if not hasattr(self, "_conflict_teachers") or not self._conflict_teachers:
                    self._conflict_teachers = {
                        req.teacher.name
                        for req in self._conflict_cls.subject_requirements
                    }

        print(f"[DEBUG] finished in {elapsed:.2f}s, {call_count[0]:,} calls, result={result}")
        print(f"[DEBUG] nogood cache size: {len(_nogood_cache):,}")
        return result

    # ── Consecutive check ──────────────────────────────────────────────────────

    def _check_consecutive(self, cls, subject, day: int, hour: int, max_consecutive: int) -> bool:
        if subject is None or max_consecutive >= 30:
            return True

        subj_name = subject.name

        run_before = 0
        for h in range(hour - 1, -1, -1):
            if cls.schedule.get_subject_name(day, h) == subj_name:
                run_before += 1
            else:
                break

        run_after = 0
        for h in range(hour + 1, 8):
            if cls.schedule.get_subject_name(day, h) == subj_name:
                run_after += 1
            else:
                break

        if run_before + 1 + run_after > max_consecutive:
            return False

        if run_before == 0 and run_after == 0:
            for h in range(8):
                if h != hour and cls.schedule.get_subject_name(day, h) == subj_name:
                    return False
        elif run_before > 0:
            for h in range(0, hour - run_before):
                if cls.schedule.get_subject_name(day, h) == subj_name:
                    return False
        elif run_after > 0:
            for h in range(hour + run_after + 1, 8):
                if cls.schedule.get_subject_name(day, h) == subj_name:
                    return False

        return True

    # ── low-level assign / unassign ────────────────────────────────────────────

    def _assign(self, cls, req, req_idx, rem, day, hour, teacher_remaining=None):
        sc = ScheduledClass(
            school_class=cls,
            subject=req.subject,
            teacher=req.teacher,
            room=req.room,
            day=day,
            hour=hour,
        )
        cls.schedule.assign(day, hour, sc)
        req.teacher.schedule.assign(day, hour, sc)
        req.room.schedule.assign(day, hour, sc)
        rem[req_idx] -= 1
        if teacher_remaining is not None:
            teacher_remaining[id(req.teacher)] -= 1

    def _unassign(self, cls, req, req_idx, rem, day, hour, teacher_remaining=None):
        cls.schedule.clear(day, hour)
        req.teacher.schedule.clear(day, hour)
        req.room.schedule.clear(day, hour)
        rem[req_idx] += 1
        if teacher_remaining is not None:
            teacher_remaining[id(req.teacher)] += 1

    def _slot_free(self, cls, teacher, room, day, hour, subject=None, max_consecutive=30):
        if not (
            cls.schedule.is_free(day, hour)
            and teacher.schedule.is_free(day, hour)
            and room.schedule.is_free(day, hour)
        ):
            return False
        for c in teacher.constraints:
            if isinstance(c, UnavailableTimePeriodConstraint):
                if (day, hour) in c._unavailable_set:
                    return False
        return self._check_consecutive(cls, subject, day, hour, max_consecutive)

    @staticmethod
    def _get_max_consecutive(cls) -> dict[str, int]:
        result: dict[str, int] = {}
        for req in cls.subject_requirements:
            for c in req.subject.constraints:
                if isinstance(c, MaxConsecutiveClassesConstraint):
                    result[req.subject.name] = c.max_classes
        return result

    def _check_hard(self, cls, teacher, room) -> bool:
        entities = {"school_class": cls, "teacher": teacher, "room": room}
        for c in self._hard_constraints:
            if hasattr(c, "affects") and not c.affects(**entities):
                continue
            if not c.check(self.context):
                return False
        return True

    # ── constraint collection ──────────────────────────────────────────────────

    def _collect_constraints(self) -> tuple[list[Constraint], list[Constraint]]:
        seen: set[int] = set()
        hard: list[Constraint] = []
        soft: list[Constraint] = []

        all_c: list[Constraint] = []
        for cls in self.context.classes:
            all_c.extend(cls.constraints)
            for req in cls.subject_requirements:
                all_c.extend(req.subject.constraints)
        for t in self.context.teachers:
            all_c.extend(t.constraints)
        for r in self.context.rooms:
            all_c.extend(r.constraints)

        for c in all_c:
            cid = id(c)
            if cid in seen:
                continue
            seen.add(cid)
            if isinstance(c, (
                MaxConsecutiveClassesConstraint,
                UnavailableTimePeriodConstraint,
                MaxDailyClassCount,
                MinDailyClassCount,
            )):
                continue
            if type(c).check is not Constraint.check:
                hard.append(c)
            elif type(c).score is not Constraint.score:
                soft.append(c)

        return hard, soft

    def _total_soft_score(self) -> int:
        return sum(c.score(self.context) for c in self._soft_constraints)

    # ── clear / snapshot / restore ─────────────────────────────────────────────

    def _clear_all(self) -> None:
        for cls in self.context.classes:
            cls.schedule.clear_all()
        for t in self.context.teachers:
            t.schedule.clear_all()
        for r in self.context.rooms:
            r.schedule.clear_all()

    def _snapshot(self) -> dict:
        snap = {}
        for cls in self.context.classes:
            k = ("class", id(cls))
            snap[k] = cls.schedule.snapshot() if hasattr(cls.schedule, "snapshot") else dict(cls.schedule.slots)
        for t in self.context.teachers:
            k = ("teacher", id(t))
            snap[k] = t.schedule.snapshot() if hasattr(t.schedule, "snapshot") else dict(t.schedule.slots)
        for r in self.context.rooms:
            k = ("room", id(r))
            snap[k] = r.schedule.snapshot() if hasattr(r.schedule, "snapshot") else dict(r.schedule.slots)
        return snap

    def _restore_best(self) -> None:
        for cls in self.context.classes:
            data = self._best_slots[("class", id(cls))]
            if hasattr(cls.schedule, "restore"):
                cls.schedule.restore(data)
            else:
                cls.schedule.slots = data
        for t in self.context.teachers:
            data = self._best_slots[("teacher", id(t))]
            if hasattr(t.schedule, "restore"):
                t.schedule.restore(data)
            else:
                t.schedule.slots = data
        for r in self.context.rooms:
            data = self._best_slots[("room", id(r))]
            if hasattr(r.schedule, "restore"):
                r.schedule.restore(data)
            else:
                r.schedule.slots = data