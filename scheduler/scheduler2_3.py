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


class Scheduler:
    def __init__(self, context: SchedulerContext):
        self.context = context
        self._hard_constraints, self._soft_constraints = self._collect_constraints()

    # ── Public API ─────────────────────────────────────────────────────────────

    def solve(self) -> bool:
        success = self._solve_compact()
        if not success:
            self._clear_all()
        return success

    def solve_top_n(self, max_solutions: int = 10) -> bool:
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

    def solve_best(self, time_limit: float = 30.0) -> bool:
        self._deadline = time.monotonic() + time_limit
        self._best_score = -1
        self._best_slots: dict = {}
        self._solve_compact(collect_best=True, use_deadline=True)
        if self._best_slots:
            self._restore_best()
            return True
        self._clear_all()
        return False

    # ── Core solver ────────────────────────────────────────────────────────────

    def _solve_compact(
        self,
        collect_best: bool = False,
        use_deadline: bool = False,
    ) -> bool:

        classes = sorted(
            self.context.classes,
            key=lambda c: sum(r.sessions_per_week for r in c.subject_requirements),
            reverse=True,
        )

        n_classes = len(classes)

        remaining: list[dict[int, int]] = [
            {i: req.sessions_per_week for i, req in enumerate(cls.subject_requirements)}
            for cls in classes
        ]

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

        # Build teacher_reqs and teacher_remaining for the initial ordering
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

        # Build teacher_free BEFORE class_priority so the sort can use it
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

        # Rebuild all index-dependent structures after re-sort
        compact_flag   = [cls.grade not in NON_COMPACT_GRADES for cls in classes]
        remaining      = [
            {i: req.sessions_per_week for i, req in enumerate(cls.subject_requirements)}
            for cls in classes
        ]
        max_consec_map = [self._get_max_consecutive(cls) for cls in classes]

        # ── daily cap (max) and floor (min) per class ──────────────────────────
        # Both are extracted once and used natively in the backtracker,
        # bypassing _check_hard entirely for these two constraints.
        max_daily_cap = []
        min_daily_floor = []   # 0 means "no minimum enforced"
        for cls in classes:
            cap = 8
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
            """
            Forward check for the class currently being scheduled.

            days_left   : days still available INCLUDING today (5 - current_day).
            today_count : sessions already placed on the current day (= hour in
                          compact mode).  When the floor check reasons about
                          "remaining sessions across days_left days", today's
                          already-placed sessions are part of today's block and
                          must not be treated as if they need a fresh day.

            The key invariant for the floor check:
              - today_count > 0  → today is an open, partially-filled day.
                The open day will eventually hold today_count + X more sessions
                where X >= max(0, floor - today_count).
                So effective_remaining for the pure "future days" calculation is
                total_rem minus what today still NEEDS to reach floor:
                  today_must_still_place = max(0, floor - today_count)
                  future_rem = total_rem - today_must_still_place
                The future_rem sessions must fit in (days_left - 1) future days
                each holding floor..cap sessions.
              - today_count == 0 → today has not started yet; treat it like any
                other day.
            """
            rem   = remaining[cls_idx]
            cap   = max_daily_cap[cls_idx]
            floor = min_daily_floor[cls_idx]

            total_rem = sum(rem.values())

            # Sessions must fit within the remaining days × daily cap
            if total_rem > days_left * cap:
                return False

            # Min-floor feasibility
            if floor > 0 and total_rem > 0:
                if today_count > 0:
                    # Today is partially filled.  Today's final count will be
                    # today_count + (sessions still to place today).
                    # It must end up in [floor, cap].  If today_count already
                    # exceeds cap that's caught above; if it's < floor we still
                    # have to place (floor - today_count) more today minimum.
                    today_still_needed = max(0, floor - today_count)
                    if today_still_needed > total_rem:
                        # Can't even fill today to the floor
                        return False
                    future_rem = total_rem - today_still_needed
                    future_days = days_left - 1
                    # future_rem sessions must fit in future_days days, each
                    # either skipped (0) or used (floor..cap).
                    if future_rem > 0 and future_days >= 0:
                        if future_rem > future_days * cap:
                            return False
                        min_future_days = math.ceil(future_rem / cap)
                        if min_future_days * floor > future_rem:
                            return False
                else:
                    # today_count == 0: today hasn't started; treat symmetrically
                    # with future days.
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

        # ── compact backtracker (grades 5+) ───────────────────────────────────

        def backtrack_compact(cls_idx: int, day: int, hour: int) -> bool:
            """
            cls_idx : class being scheduled
            day     : current day (0-4)
            hour    : next hour to fill within today (0-7)
                      hour=0 means start of day (nothing placed today yet)
            """
            call_count[0] += 1
            if (cls_idx, day) > deepest[0]:
                deepest[0] = (cls_idx, day)
            if call_count[0] % 100_000 == 0:
                report(cls_idx, day)

            if use_deadline and time.monotonic() > self._deadline:
                print("[DEBUG] deadline reached")
                return False

            if cls_idx == n_classes:
                return _record_solution()

            cls   = classes[cls_idx]
            rem   = remaining[cls_idx]
            total_rem = sum(rem.values())
            cap   = max_daily_cap[cls_idx]
            floor = min_daily_floor[cls_idx]

            # All sessions placed → check floor for the current day, then move on
            if total_rem == 0:
                # If we placed sessions today (hour > 0), today's block is closing
                # here. Verify it meets the minimum floor.
                if hour > 0 and floor > 0 and hour < floor:
                    return False  # today's block is too short
                print(
                    f"[DEBUG] cls{clabel(cls_idx)} done after {call_count[0]:,} calls"
                    f" → next: cls{clabel(cls_idx + 1)}"
                )
                return _dispatch(cls_idx + 1, 0, 0)

            # No days left
            if day >= 5:
                return False

            days_left = 5 - day

            # Sessions must fit in the days still available
            if total_rem > days_left * cap:
                return False

            # FIX 2: nogood cache lookup
            ng_key = (cls_idx, day, hour, _rem_sig(cls_idx))
            if ng_key in _nogood_cache:
                return False

            # ── Option B guard ─────────────────────────────────────────────────
            # We can end today (skip or close) only when the remaining sessions
            # can still fit in the days after today.
            days_after = 5 - (day + 1)
            can_end_today = (total_rem <= days_after * cap)

            # ── Min-floor guard for Option B ───────────────────────────────────
            # If we placed some sessions today (hour > 0), ending the day is only
            # valid when today's count already meets the floor.
            # If we haven't placed anything today (hour == 0), skipping is fine —
            # skipped days are not subject to the floor.
            today_count = hour  # compact mode: hour == number placed so far today
            if hour > 0 and floor > 0 and today_count < floor:
                # Today's block is too small — we MUST keep placing today.
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
                    _assign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

                    if (
                        self._check_hard(cls, teacher, room)
                        # hour+1 = sessions placed today after this assignment
                        and _can_complete_current_class(cls_idx, days_left, today_count=hour + 1)
                        and _can_complete_teacher(teacher)
                    ):
                        if backtrack_compact(cls_idx, day, hour + 1):
                            return True

                    _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

            # ── Option B: end this day's block ────────────────────────────────
            if can_end_today:
                if backtrack_compact(cls_idx, day + 1, 0):
                    return True

            _nogood_cache.add(ng_key)
            return False

        # ── free backtracker (grades 0-4) ──────────────────────────────────────

        def backtrack_free(cls_idx: int) -> bool:
            call_count[0] += 1
            if call_count[0] % 100_000 == 0:
                report(cls_idx, 0, tag="[free-mode]")

            if use_deadline and time.monotonic() > self._deadline:
                print("[DEBUG] deadline reached")
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
                return _dispatch(cls_idx + 1, 0, 0)

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

                    _assign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

                    if (
                        self._check_hard(cls, teacher, room)
                        and _can_complete_current_class(cls_idx, 5)
                        and _can_complete_teacher(teacher)
                    ):
                        if backtrack_free(cls_idx):
                            return True

                    _unassign_and_update(cls_idx, cls, req, req_idx, rem, day, hour)

                return False

            return _dispatch(cls_idx + 1, 0, 0)

        # ── shared helpers ─────────────────────────────────────────────────────

        def _dispatch(cls_idx: int, day: int, hour: int) -> bool:
            if cls_idx >= n_classes:
                return _record_solution()

            for ri, req in enumerate(classes[cls_idx].subject_requirements):
                if remaining[cls_idx][ri] == 0:
                    continue
                if not _can_complete_teacher(req.teacher):
                    return False

            if compact_flag[cls_idx]:
                return backtrack_compact(cls_idx, day, hour)
            else:
                return backtrack_free(cls_idx)

        def _record_solution() -> bool:
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

        # ── kick off ───────────────────────────────────────────────────────────
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

        # ── pre-solve cap feasibility check ───────────────────────────────────
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
            # Also check min-floor: ceil(total/cap) days each needing >= floor
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

        result = _dispatch(0, 0, 0)
        elapsed = time.monotonic() - start_time
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

        # If this slot is not adjacent to an existing run, but the subject
        # already appears somewhere else on this day, it would create a
        # second isolated run — never allowed regardless of max_consecutive.
        if run_before == 0 and run_after == 0:
            for h in range(8):
                if h != hour and cls.schedule.get_subject_name(day, h) == subj_name:
                    return False
        elif run_before > 0:
            # Extending a run leftward — check there's no earlier isolated block
            for h in range(0, hour - run_before):
                if cls.schedule.get_subject_name(day, h) == subj_name:
                    return False
        elif run_after > 0:
            # Extending a run rightward — check there's no later isolated block
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
        """
        Checks hard constraints that are NOT handled natively by the backtracker.
        MaxDailyClassCount and MinDailyClassCount are enforced natively via
        max_daily_cap / min_daily_floor, so they are excluded here.
        MaxConsecutiveClassesConstraint and UnavailableTimePeriodConstraint are
        also excluded (handled inline). This method covers any remaining custom
        hard constraints.
        """
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
            # These are all handled natively in the backtracker — skip them here
            # so _check_hard never evaluates them (avoids mid-day false failures
            # and cross-class interference).
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