from __future__ import annotations

from models.context import SchedulerContext
from models.scheduled_class import ScheduledClass
from models.constraints.subject_constraints import MaxConsecutiveClassesConstraint
from models.constraints.teacher_constraints import (
    UnavailableTimePeriodConstraint,
    MaxTeacherGapConstraint,
)
from models.constraints.class_constraints import MaxDailyClassCount, MinDailyClassCount
from ortools.sat.python import cp_model

NON_COMPACT_GRADES = {0, 1, 2, 3, 4}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"]


class Scheduler:
    """CP-SAT-only scheduler. All hand-rolled backtracking search code
    (solve/solve_top_n/solve_best/solve_portfolio and their helpers) has
    been removed — only the OR-Tools CP-SAT model and its infeasibility
    diagnostics remain."""

    def __init__(self, context: SchedulerContext):
        self.context = context

    # ── Public API ─────────────────────────────────────────────────────────────

    def solve_cpsat(self, time_limit: float = 120.0, cancel_event=None) -> bool:
        """
        Builds a CP-SAT model and solves it. Writes the result into the same
        ScheduledClass / schedule structures the rest of the app already
        reads (grids, swap, export), so no other code needs to change.
        """
        self._clear_all()
        model = cp_model.CpModel()

        classes = list(self.context.classes)
        DAYS_N, HOURS_N = 5, 8

        # ── teacher unavailable-slot lookup ─────────────────────────────────
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

        # ── decision variables: x[(ci, ri, d, h)] ──────────────────────────────
        x: dict[tuple[int, int, int, int], cp_model.IntVar] = {}
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                unavail = teacher_unavailable.get(id(req.teacher), set())
                for d in range(DAYS_N):
                    for h in range(HOURS_N):
                        if (d, h) in unavail:
                            continue
                        x[(ci, ri, d, h)] = model.NewBoolVar(f"x_{ci}_{ri}_{d}_{h}")

        # ── each requirement must total sessions_per_week placements ───────────
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                vars_ = [x[(ci, ri, d, h)] for d in range(DAYS_N) for h in range(HOURS_N)
                         if (ci, ri, d, h) in x]
                model.Add(sum(vars_) == req.sessions_per_week)

        # ── class: at most one lesson per (day,hour) ────────────────────────────
        for ci, cls in enumerate(classes):
            for d in range(DAYS_N):
                for h in range(HOURS_N):
                    vars_ = [x[(ci, ri, d, h)] for ri in range(len(cls.subject_requirements))
                             if (ci, ri, d, h) in x]
                    if vars_:
                        model.Add(sum(vars_) <= 1)

        # ── teacher: at most one lesson per (day,hour) across all classes ──────
        teacher_slots: dict[tuple[int, int, int], list] = {}
        for (ci, ri, d, h), var in x.items():
            tid = id(classes[ci].subject_requirements[ri].teacher)
            teacher_slots.setdefault((tid, d, h), []).append(var)
        for vars_ in teacher_slots.values():
            if len(vars_) > 1:
                model.Add(sum(vars_) <= 1)

        # ── room: at most one lesson per (day,hour) ─────────────────────────────
        room_slots: dict[tuple[int, int, int], list] = {}
        for (ci, ri, d, h), var in x.items():
            rid = id(classes[ci].subject_requirements[ri].room)
            room_slots.setdefault((rid, d, h), []).append(var)
        for vars_ in room_slots.values():
            if len(vars_) > 1:
                model.Add(sum(vars_) <= 1)

        # ── max-consecutive-block rule per (class, req) per day ─────────────────
        # Two separate rules, both always active:
        #  (1) contiguity: same-subject sessions on the same day must form ONE
        #      unbroken block — no splitting (e.g. hour 0 and hour 7). This
        #      applies regardless of sessions_per_week / max_consecutive.
        #  (2) length cap: that single block may not exceed max_consecutive
        #      hours (skipped when max_consecutive >= HOURS_N, i.e. no cap).

        # ── teacher max-gap constraint ────────────────────────────────────────
        self._add_teacher_gap_constraints(model, x, classes, DAYS_N, HOURS_N)
        max_consec_map = [self._get_max_consecutive(cls) for cls in classes]
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                mc = max_consec_map[ci].get(req.subject.name, 30)

                for d in range(DAYS_N):
                    hours_here = [h for h in range(HOURS_N) if (ci, ri, d, h) in x]
                    if len(hours_here) < 2:
                        continue

                    # (1) contiguity — at most one "start of block" per day.
                    starts = []
                    prev_var = None
                    for h in hours_here:
                        var_h = x[(ci, ri, d, h)]
                        if prev_var is None:
                            starts.append(var_h)
                        else:
                            start_h = model.NewBoolVar(f"start_{ci}_{ri}_{d}_{h}")
                            model.Add(start_h <= var_h)
                            model.Add(start_h <= 1 - prev_var)
                            model.Add(start_h >= var_h - prev_var)
                            starts.append(start_h)
                        prev_var = var_h
                    model.Add(sum(starts) <= 1)

                    # (2) length cap.
                    if mc < HOURS_N:
                        for i in range(len(hours_here)):
                            for j in range(i + 1, len(hours_here)):
                                h1, h2 = hours_here[i], hours_here[j]
                                if h2 - h1 >= mc:
                                    model.Add(x[(ci, ri, d, h1)] + x[(ci, ri, d, h2)] <= 1)

        # ── class daily compactness: no gaps, must start at hour 0 ─────────────
        # Grades 0-4 are exempt: their schedules are opportunistic, not a
        # finalized fixed-start schedule.
        for ci, cls in enumerate(classes):
            if cls.grade in NON_COMPACT_GRADES:
                continue
            cap, floor = 8, 0
            for c in cls.constraints:
                if isinstance(c, MaxDailyClassCount):
                    cap = min(cap, c.max_classes)
                if isinstance(c, MinDailyClassCount):
                    floor = max(floor, c.min_classes)

            for d in range(DAYS_N):
                used = []
                for h in range(HOURS_N):
                    hour_vars = [x[(ci, ri, d, h)] for ri in range(len(cls.subject_requirements))
                                 if (ci, ri, d, h) in x]
                    u = model.NewBoolVar(f"used_{ci}_{d}_{h}")
                    if hour_vars:
                        model.Add(u == sum(hour_vars))
                    else:
                        model.Add(u == 0)
                    used.append(u)

                for h in range(HOURS_N - 1):
                    model.Add(used[h] >= used[h + 1])

                day_total = sum(used)
                active = used[0]
                if floor > 0:
                    model.Add(day_total >= floor).OnlyEnforceIf(active)
                model.Add(day_total <= cap).OnlyEnforceIf(active)
                model.Add(day_total == 0).OnlyEnforceIf(active.Not())

        # ── solve ────────────────────────────────────────────────────────────
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_search_workers = 8

        class _CancelCb(cp_model.CpSolverSolutionCallback):
            def __init__(self, ev):
                super().__init__()
                self._ev = ev

            def OnSolutionCallback(self):
                if self._ev is not None and self._ev.is_set():
                    self.StopSearch()

        cb = _CancelCb(cancel_event)
        status = solver.Solve(model, cb)
        print(f"[CP-SAT] status={solver.StatusName(status)} "
              f"time={solver.WallTime():.1f}s")

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return False

        # ── write the solution into the existing schedule structures ───────────
        for (ci, ri, d, h), var in x.items():
            if solver.Value(var):
                cls = classes[ci]
                req = cls.subject_requirements[ri]
                sc = ScheduledClass(
                    school_class=cls, subject=req.subject, teacher=req.teacher,
                    room=req.room, day=d, hour=h,
                )
                cls.schedule.assign(d, h, sc)
                req.teacher.schedule.assign(d, h, sc)
                req.room.schedule.assign(d, h, sc)

        return True

    def diagnose_infeasibility(self, time_limit: float = 60.0) -> None:
        """
        Rebuilds the same model as solve_cpsat, but wraps every class/day
        compactness+floor/cap block behind an assumption literal. If the
        model is infeasible, asks CP-SAT for a minimal set of assumptions
        that are jointly unsatisfiable — i.e. the exact class/day rules
        that conflict with each other or with teacher availability.
        """
        model = cp_model.CpModel()
        classes = list(self.context.classes)
        DAYS_N, HOURS_N = 5, 8

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

        x = {}
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                unavail = teacher_unavailable.get(id(req.teacher), set())
                for d in range(DAYS_N):
                    for h in range(HOURS_N):
                        if (d, h) in unavail:
                            continue
                        x[(ci, ri, d, h)] = model.NewBoolVar(f"x_{ci}_{ri}_{d}_{h}")

        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                vars_ = [x[(ci, ri, d, h)] for d in range(DAYS_N) for h in range(HOURS_N)
                         if (ci, ri, d, h) in x]
                model.Add(sum(vars_) == req.sessions_per_week)

        for ci, cls in enumerate(classes):
            for d in range(DAYS_N):
                for h in range(HOURS_N):
                    vars_ = [x[(ci, ri, d, h)] for ri in range(len(cls.subject_requirements))
                             if (ci, ri, d, h) in x]
                    if vars_:
                        model.Add(sum(vars_) <= 1)

        teacher_slots = {}
        for (ci, ri, d, h), var in x.items():
            tid = id(classes[ci].subject_requirements[ri].teacher)
            teacher_slots.setdefault((tid, d, h), []).append(var)
        for vars_ in teacher_slots.values():
            if len(vars_) > 1:
                model.Add(sum(vars_) <= 1)

        room_slots = {}
        for (ci, ri, d, h), var in x.items():
            rid = id(classes[ci].subject_requirements[ri].room)
            room_slots.setdefault((rid, d, h), []).append(var)
        for vars_ in room_slots.values():
            if len(vars_) > 1:
                model.Add(sum(vars_) <= 1)

        # ── max-consecutive-block rule (same two rules as solve_cpsat) ─────────

        # ── teacher max-gap constraint ────────────────────────────────────────
        self._add_teacher_gap_constraints(model, x, classes, DAYS_N, HOURS_N)
        max_consec_map = [self._get_max_consecutive(cls) for cls in classes]
        for ci, cls in enumerate(classes):
            for ri, req in enumerate(cls.subject_requirements):
                mc = max_consec_map[ci].get(req.subject.name, 30)

                for d in range(DAYS_N):
                    hours_here = [h for h in range(HOURS_N) if (ci, ri, d, h) in x]
                    if len(hours_here) < 2:
                        continue

                    starts = []
                    prev_var = None
                    for h in hours_here:
                        var_h = x[(ci, ri, d, h)]
                        if prev_var is None:
                            starts.append(var_h)
                        else:
                            start_h = model.NewBoolVar(f"start_{ci}_{ri}_{d}_{h}")
                            model.Add(start_h <= var_h)
                            model.Add(start_h <= 1 - prev_var)
                            model.Add(start_h >= var_h - prev_var)
                            starts.append(start_h)
                        prev_var = var_h
                    model.Add(sum(starts) <= 1)

                    if mc < HOURS_N:
                        for i in range(len(hours_here)):
                            for j in range(i + 1, len(hours_here)):
                                h1, h2 = hours_here[i], hours_here[j]
                                if h2 - h1 >= mc:
                                    model.Add(x[(ci, ri, d, h1)] + x[(ci, ri, d, h2)] <= 1)

        # ── compactness, gated behind assumption literals ───────────────────
        # Grades 0-4 are exempt entirely — no assumption literal, so they
        # can never show up in a core.
        assumptions = {}
        for ci, cls in enumerate(classes):
            if cls.grade in NON_COMPACT_GRADES:
                continue
            cap, floor = 8, 0
            for c in cls.constraints:
                if isinstance(c, MaxDailyClassCount):
                    cap = min(cap, c.max_classes)
                if isinstance(c, MinDailyClassCount):
                    floor = max(floor, c.min_classes)

            for d in range(DAYS_N):
                assum = model.NewBoolVar(f"assum_compact_{ci}_{d}")
                assumptions[(ci, d)] = assum

                used = []
                for h in range(HOURS_N):
                    hour_vars = [x[(ci, ri, d, h)] for ri in range(len(cls.subject_requirements))
                                 if (ci, ri, d, h) in x]
                    u = model.NewBoolVar(f"used_{ci}_{d}_{h}")
                    if hour_vars:
                        model.Add(u == sum(hour_vars))
                    else:
                        model.Add(u == 0)
                    used.append(u)

                for h in range(HOURS_N - 1):
                    model.Add(used[h] >= used[h + 1]).OnlyEnforceIf(assum)

                day_total = sum(used)
                active = used[0]
                if floor > 0:
                    model.Add(day_total >= floor).OnlyEnforceIf([assum, active])
                model.Add(day_total <= cap).OnlyEnforceIf([assum, active])
                model.Add(day_total == 0).OnlyEnforceIf([assum, active.Not()])

        model.AddAssumptions(list(assumptions.values()))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        status = solver.Solve(model)

        print(f"[Diagnose] status={solver.StatusName(status)}")
        if status == cp_model.INFEASIBLE:
            core = solver.SufficientAssumptionsForInfeasibility()
            rev = {v.Index(): k for k, v in assumptions.items()}
            print(f"[Diagnose] Minimal conflicting assumptions ({len(core)}):")
            for lit in core:
                idx = lit.Index() if hasattr(lit, "Index") else lit
                ci, d = rev[idx]
                c = classes[ci]
                print(f"  cls{c.grade}{c.version} / {DAY_NAMES[d]}")
        else:
            print("[Diagnose] Model is feasible on its own — infeasibility must come "
                  "from something not modeled here (double-check solve_cpsat matches "
                  "this function exactly).")

    # ── teacher-gap constraint ───────────────────────────────────────────────

    @staticmethod
    def _teacher_gap_config(classes) -> dict[int, tuple[int, int]]:
        """tid -> (max_gap, max_gaps_per_day) for every teacher that carries
        a MaxTeacherGapConstraint."""
        cfg: dict[int, tuple[int, int]] = {}
        for cls in classes:
            for req in cls.subject_requirements:
                tid = id(req.teacher)
                if tid in cfg:
                    continue
                for c in req.teacher.constraints:
                    if isinstance(c, MaxTeacherGapConstraint):
                        cfg[tid] = (c.max_gap, c.max_gaps_per_day)
                        break
        return cfg

    def _add_teacher_gap_constraints(self, model, x, classes, DAYS_N, HOURS_N) -> None:
        """
        Enforces MaxTeacherGapConstraint: within a teacher's working span on a
        given day (from their first lesson to their last lesson), no run of
        empty hours may exceed `max_gap`, and the number of separate gap runs
        may not exceed `max_gaps_per_day`.

        Modeled per (teacher, day) with:
          occ[h]   — teacher has a lesson at hour h
          upto[h]  — teacher has a lesson at or before h   (prefix OR)
          frm[h]   — teacher has a lesson at or after h    (suffix OR)
          gap[h]   — h is inside the [first, last] span but empty
          start[h] — h is the first hour of a gap run
        """
        gap_cfg = self._teacher_gap_config(classes)
        if not gap_cfg:
            return

        teacher_slot_vars: dict[tuple[int, int, int], list] = {}
        for (ci, ri, d, h), var in x.items():
            tid = id(classes[ci].subject_requirements[ri].teacher)
            teacher_slot_vars.setdefault((tid, d, h), []).append(var)

        for tid, (max_gap, max_gaps_per_day) in gap_cfg.items():
            if max_gap >= HOURS_N - 1:
                continue  # effectively unrestricted — nothing to enforce

            for d in range(DAYS_N):
                occ = []
                for h in range(HOURS_N):
                    vars_ = teacher_slot_vars.get((tid, d, h), [])
                    if not vars_:
                        occ.append(0)
                    elif len(vars_) == 1:
                        occ.append(vars_[0])
                    else:
                        o = model.NewBoolVar(f"occ_{tid}_{d}_{h}")
                        model.Add(o == sum(vars_))
                        occ.append(o)

                upto = []
                for h in range(HOURS_N):
                    if h == 0:
                        u = occ[0]
                    else:
                        u = model.NewBoolVar(f"upto_{tid}_{d}_{h}")
                        model.Add(u >= occ[h])
                        model.Add(u >= upto[h - 1])
                        model.Add(u <= occ[h] + upto[h - 1])
                    upto.append(u)

                frm = [None] * HOURS_N
                for h in range(HOURS_N - 1, -1, -1):
                    if h == HOURS_N - 1:
                        f = occ[h]
                    else:
                        f = model.NewBoolVar(f"from_{tid}_{d}_{h}")
                        model.Add(f >= occ[h])
                        model.Add(f >= frm[h + 1])
                        model.Add(f <= occ[h] + frm[h + 1])
                    frm[h] = f

                gap = []
                for h in range(HOURS_N):
                    r = model.NewBoolVar(f"inspan_{tid}_{d}_{h}")
                    model.Add(r <= upto[h])
                    model.Add(r <= frm[h])
                    model.Add(r >= upto[h] + frm[h] - 1)

                    g = model.NewBoolVar(f"gap_{tid}_{d}_{h}")
                    model.Add(g <= r)
                    model.Add(g <= 1 - occ[h])
                    model.Add(g >= r - occ[h])
                    gap.append(g)

                # run-length cap: no window of (max_gap + 1) consecutive
                # hours may be entirely gap hours.
                for i in range(HOURS_N - max_gap):
                    model.Add(sum(gap[i:i + max_gap + 1]) <= max_gap)

                # cap on number of distinct gap runs per day.
                if max_gaps_per_day < HOURS_N:
                    starts = []
                    for h in range(HOURS_N):
                        if h == 0:
                            s = gap[0]
                        else:
                            s = model.NewBoolVar(f"gstart_{tid}_{d}_{h}")
                            model.Add(s <= gap[h])
                            model.Add(s <= 1 - gap[h - 1])
                            model.Add(s >= gap[h] - gap[h - 1])
                        starts.append(s)
                    model.Add(sum(starts) <= max_gaps_per_day)

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_max_consecutive(cls) -> dict[str, int]:
        result: dict[str, int] = {}
        for req in cls.subject_requirements:
            for c in req.subject.constraints:
                if isinstance(c, MaxConsecutiveClassesConstraint):
                    result[req.subject.name] = c.max_classes
        return result

    def _clear_all(self) -> None:
        for cls in self.context.classes:
            cls.schedule.clear_all()
        for t in self.context.teachers:
            t.schedule.clear_all()
        for r in self.context.rooms:
            r.schedule.clear_all()