"""
structural_check.py  —  finds every teacher whose day-availability pattern
is incompatible with the compact-mode floor/cap constraints of the classes
they teach.

The key insight: a teacher available on only K days must spread their
sessions_per_week across those K days.  But compact classes have a
MinDailyClassCount floor, so each "active day" for a class must contain
at least `floor` sessions.  If multiple classes share the same teacher on
the same scarce days, the combined floor demand can exceed what fits.

Run: python structural_check.py
"""

from __future__ import annotations
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from collections import defaultdict

from models.subject import Subject
from models.teacher import Teacher
from models.room import Room
from models.school_class import SchoolClass, SubjectRequirement
from models.scheduled_class import ScheduledClass
from models.context import SchedulerContext
from models.schedule import Schedule
from models.constraints.class_constraints import MinDailyClassCount, MaxDailyClassCount
from models.constraints.subject_constraints import MaxConsecutiveClassesConstraint
from models.constraints.teacher_constraints import (
    UnavailableTimePeriodConstraint, MaxTeacherGapConstraint,
)

Schedule.model_rebuild()
ScheduledClass.model_rebuild()
Teacher.model_rebuild()
Room.model_rebuild()
SchoolClass.model_rebuild()
SchedulerContext.model_rebuild()

EXCEL_PATH   = "test_schedule.xlsx"
DAYS         = 5
HOURS        = 8
DAY_COL_MAP  = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
DAY_NAMES    = ["Mon", "Tue", "Wed", "Thu", "Fri"]
NON_COMPACT  = {0, 1, 2, 3, 4}

# ── load & build context (identical to main.py) ───────────────────────────────
teachers_df       = pd.read_excel(EXCEL_PATH, sheet_name="teachers")
classes_df        = pd.read_excel(EXCEL_PATH, sheet_name="school_schedule")
teachers_df.columns = teachers_df.columns.str.strip()
classes_df.columns  = classes_df.columns.str.strip()

teacher_availability: dict[str, dict[str, int]] = {}
teacher_max_gap:      dict[str, int]             = {}
for _, row in teachers_df.iterrows():
    name = str(row["Teacher"]).strip()
    teacher_availability[name] = {
        d: int(row[d]) for d in DAY_COL_MAP if d in row.index
    }
    teacher_max_gap[name] = (
        int(row["MaxGap"])
        if "MaxGap" in row.index and pd.notna(row["MaxGap"]) else 1
    )

subjects_map: dict[str, Subject] = {}
teachers_map: dict[str, Teacher] = {}
rooms_map:    dict[str, Room]    = {}

for _, row in classes_df.iterrows():
    sn, tn, cn = (str(row[k]).strip() for k in ("Subject", "Teacher", "ClassName"))
    if sn not in subjects_map:
        subjects_map[sn] = Subject(name=sn, relevance=5)
    if tn not in teachers_map:
        teachers_map[tn] = Teacher(name=tn, subjects=[])
    t = teachers_map[tn]
    s = subjects_map[sn]
    if s not in t.subjects:
        t.subjects.append(s)
    if cn not in rooms_map:
        rooms_map[cn] = Room(name=f"Room {cn}")

school_classes_map: dict[str, SchoolClass] = {}
for class_name, group in classes_df.groupby("ClassName"):
    class_name = str(class_name).strip()
    room       = rooms_map[class_name]
    reqs, total = [], 0
    for _, row in group.iterrows():
        sn, tn = str(row["Subject"]).strip(), str(row["Teacher"]).strip()
        s = int(row["NumberOfClasses"])
        reqs.append(SubjectRequirement(
            subject=Subject(name=sn, relevance=5),
            teacher=teachers_map[tn],
            sessions_per_week=s, room=room,
        ))
        total += s
    raw     = class_name
    version = raw[-1] if raw and raw[-1].isalpha() else ""
    gs      = raw[:-1] if version else raw
    grade   = int(gs) if gs.isdigit() else 0
    school_classes_map[class_name] = SchoolClass(
        grade=grade, version=version,
        total_class_sessions=total,
        subject_requirements=reqs, constraints=[],
    )

context = SchedulerContext(
    classes=list(school_classes_map.values()),
    teachers=list(teachers_map.values()),
    rooms=list(rooms_map.values()),
)

for teacher in context.teachers:
    avail = teacher_availability.get(teacher.name, {})
    unavail_slots = [
        (DAY_COL_MAP[dc], h)
        for dc, di in DAY_COL_MAP.items()
        for h in range(HOURS)
        if not avail.get(dc, 1)
    ]
    mg = teacher_max_gap.get(teacher.name, 1)
    cs = [MaxTeacherGapConstraint(priority=10, teacher=teacher,
                                  max_gap=mg, max_gaps_per_day=1)]
    if unavail_slots:
        cs.append(UnavailableTimePeriodConstraint(
            priority=10, teacher=teacher, unavailable_slots=unavail_slots))
    teacher.constraints = cs

for cls in context.classes:
    mn = int(cls.total_class_sessions / 5 - 1)
    mx = int(cls.total_class_sessions / 5 + 1)
    cls.constraints = [
        MaxDailyClassCount(priority=10, max_classes=mx, school_class=cls),
        MinDailyClassCount(priority=10, min_classes=mn, school_class=cls),
    ]
    for req in cls.subject_requirements:
        mc = 2 if req.sessions_per_week < 6 else 30
        req.subject.constraints = [
            MaxConsecutiveClassesConstraint(priority=10,
                subject=req.subject, max_classes=mc),
        ]

# ── build teacher unavailability sets ────────────────────────────────────────
teacher_unavailable: dict[int, set] = {}
for cls in context.classes:
    for req in cls.subject_requirements:
        tid = id(req.teacher)
        if tid not in teacher_unavailable:
            unavail: set = set()
            for c in req.teacher.constraints:
                if isinstance(c, UnavailableTimePeriodConstraint):
                    unavail = c._unavailable_set
                    break
            teacher_unavailable[tid] = unavail

# ── per-teacher: which days are available at all ──────────────────────────────
def available_days(teacher) -> set[int]:
    unavail = teacher_unavailable.get(id(teacher), set())
    return {d for d in range(DAYS) if any((d, h) not in unavail for h in range(HOURS))}

# ── per-class: floor and cap ──────────────────────────────────────────────────
def get_floor_cap(cls) -> tuple[int, int]:
    floor, cap = 0, 8
    for c in cls.constraints:
        if isinstance(c, MinDailyClassCount):
            floor = max(floor, c.min_classes)
        if isinstance(c, MaxDailyClassCount):
            cap   = min(cap,   c.max_classes)
    return floor, cap

# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
print("STRUCTURAL FEASIBILITY CHECK")
print("=" * 76)

issues_found = False

# ── Check 1: teacher day-availability vs total load ──────────────────────────
print("\n── CHECK 1: Teacher available-day capacity ───────────────────────────")
print("   Each teacher's sessions must fit within their available days × 8h.\n")

for teacher in sorted(context.teachers, key=lambda t: t.name):
    tid      = id(teacher)
    avail_d  = sorted(available_days(teacher))
    n_days   = len(avail_d)
    max_cap  = n_days * HOURS

    # All sessions across all classes
    all_reqs = [
        (cn, req)
        for cn, cls in school_classes_map.items()
        for req in cls.subject_requirements
        if id(req.teacher) == tid
    ]
    total_sessions = sum(r.sessions_per_week for _, r in all_reqs)
    if total_sessions == 0:
        continue

    day_names_avail = [DAY_NAMES[d] for d in avail_d]
    ok = total_sessions <= max_cap
    flag = "" if ok else "  *** HARD INFEASIBLE ***"
    print(
        f"  {teacher.name:30s}  days={day_names_avail}  "
        f"need={total_sessions:3d}  max_fit={max_cap:3d}  {'✓' if ok else '✗'}{flag}"
    )
    if not ok:
        issues_found = True
        for cn, req in sorted(all_reqs):
            print(f"    ↳ {cn}: {req.subject.name} × {req.sessions_per_week}")

# ── Check 2: compact-class floor vs teacher day availability ─────────────────
print("\n── CHECK 2: Compact-class floor constraint vs teacher day scarcity ───")
print("   For compact classes: each USED day must have >= floor sessions.")
print("   If a teacher is only available on K days, and the class needs N")
print("   sessions, then ceil(N/cap) days will be used, each requiring")
print("   >= floor sessions.  This can be infeasible even when raw slots OK.\n")

for cn, cls in sorted(school_classes_map.items()):
    if cls.grade in NON_COMPACT:
        continue
    floor, cap = get_floor_cap(cls)
    if floor == 0:
        continue

    for req in cls.subject_requirements:
        teacher   = req.teacher
        tid       = id(teacher)
        avail_d   = available_days(teacher)
        n         = req.sessions_per_week

        if n == 0:
            continue

        # Days the teacher is available AND the class could use
        # (class has no pre-assigned slots so we just use teacher availability)
        usable_days = len(avail_d)

        # Minimum days needed given cap
        min_days_needed = math.ceil(n / cap)

        # If we use min_days_needed days, each needs >= floor sessions.
        # Total minimum sessions = min_days_needed * floor
        min_sessions_due_to_floor = min_days_needed * floor

        # If total sessions is less than min required by floor: infeasible
        if min_sessions_due_to_floor > n:
            print(
                f"  *** FLOOR INFEASIBLE *** {cn} {req.subject.name}"
                f"({teacher.name}): "
                f"needs={n}, cap={cap} → min {min_days_needed} day(s) × "
                f"floor={floor} = {min_sessions_due_to_floor} > {n}"
            )
            issues_found = True

        # Also check: does the teacher have enough available days to spread N
        # sessions such that no day exceeds cap?
        if usable_days < min_days_needed:
            print(
                f"  *** DAY SHORTAGE *** {cn} {req.subject.name}"
                f"({teacher.name}): "
                f"needs {min_days_needed} days but teacher only available "
                f"on {usable_days} days ({[DAY_NAMES[d] for d in sorted(avail_d)]})"
            )
            issues_found = True

if not issues_found:
    print("  (no issues found in this check)")

# ── Check 3: shared teacher day-column pressure ───────────────────────────────
print("\n── CHECK 3: Shared-teacher day-column pressure ───────────────────────")
print("   For each teacher, on each available day: how many sessions from")
print("   ALL classes must land on that day?  8 slots max per day.\n")

# Build: teacher → day → list of (class, subject, sessions_that_could_land_here)
# "Could land here" = teacher available that day.
# We then compute: if sessions are distributed as evenly as possible across
# available days, does any day get overloaded?

for teacher in sorted(context.teachers, key=lambda t: t.name):
    tid     = id(teacher)
    avail_d = sorted(available_days(teacher))
    if not avail_d:
        continue

    all_reqs = [
        (cn, cls, req)
        for cn, cls in school_classes_map.items()
        for req in cls.subject_requirements
        if id(req.teacher) == tid
    ]
    if not all_reqs:
        continue

    total_sessions = sum(r.sessions_per_week for _, _, r in all_reqs)
    n_days         = len(avail_d)

    # Minimum sessions per day if distributed evenly (ceiling)
    min_per_day_ceil = math.ceil(total_sessions / n_days)

    if min_per_day_ceil > HOURS:
        print(
            f"  *** OVERLOADED *** {teacher.name}: {total_sessions} sessions "
            f"across {n_days} days → min {min_per_day_ceil}/day > {HOURS} slots/day"
        )
        issues_found = True
        for cn, cls, req in sorted(all_reqs):
            floor, cap = get_floor_cap(cls)
            print(
                f"    ↳ {cn} (floor={floor},cap={cap}): "
                f"{req.subject.name} × {req.sessions_per_week}"
            )

    # For scarce teachers (2-3 days): also check per-day floor pressure
    # from compact classes
    if n_days <= 3:
        day_floors: dict[int, int] = defaultdict(int)  # day → min sessions needed

        for cn, cls, req in all_reqs:
            if cls.grade in NON_COMPACT:
                continue
            floor, cap = get_floor_cap(cls)
            n = req.sessions_per_week
            if n == 0 or floor == 0:
                continue
            # Spread this class's sessions across available days as evenly as
            # possible, then each active day contributes its floor to that day's
            # minimum demand.
            min_d_needed = math.ceil(n / cap)
            # Those min_d_needed days each need floor sessions.  Assign the
            # busiest days (worst case for pressure analysis).
            for d in avail_d[:min_d_needed]:
                day_floors[d] += floor

        overloaded_days = {
            d: v for d, v in day_floors.items() if v > HOURS
        }
        if overloaded_days:
            print(
                f"  *** DAY-FLOOR OVERLOAD *** {teacher.name} "
                f"(avail: {[DAY_NAMES[d] for d in avail_d]}):"
            )
            issues_found = True
            for d, v in sorted(overloaded_days.items()):
                print(
                    f"    {DAY_NAMES[d]}: combined floor demand = {v} "
                    f"> {HOURS} slots — impossible"
                )
            # Show which classes contribute to this day
            for cn, cls, req in sorted(all_reqs, key=lambda x: (x[0], x[1], x[2].subject.name)):
                if cls.grade in NON_COMPACT:
                    continue
                floor, cap = get_floor_cap(cls)
                if floor == 0 or req.sessions_per_week == 0:
                    continue
                print(
                    f"    ↳ {cn} (floor={floor},cap={cap}): "
                    f"{req.subject.name} × {req.sessions_per_week}"
                )

# ── Check 4: NASTUTA DELIA specific deep analysis ────────────────────────────
print("\n── CHECK 4: Deep analysis of the tightest teacher (auto-detected) ───")

# Find the teacher with the worst available_days / total_sessions ratio
worst_teacher = None
worst_ratio   = float("inf")
for teacher in context.teachers:
    tid    = id(teacher)
    avail  = sorted(available_days(teacher))
    total  = sum(
        req.sessions_per_week
        for cls in context.classes
        for req in cls.subject_requirements
        if id(req.teacher) == tid
    )
    if total == 0:
        continue
    ratio = len(avail) * HOURS / total
    if ratio < worst_ratio:
        worst_ratio   = ratio
        worst_teacher = teacher

if worst_teacher:
    tid    = id(worst_teacher)
    avail  = sorted(available_days(worst_teacher))
    unavail = teacher_unavailable.get(tid, set())
    print(f"\n  Tightest teacher: {worst_teacher.name}")
    print(f"  Available days:   {[DAY_NAMES[d] for d in avail]}")
    print(f"  Slot ratio:       {worst_ratio:.2f}x  (1.0 = exactly enough)")

    classes_for_teacher = [
        (cn, cls, req)
        for cn, cls in school_classes_map.items()
        for req in cls.subject_requirements
        if id(req.teacher) == tid
    ]
    total_s = sum(r.sessions_per_week for _, _, r in classes_for_teacher)
    print(f"  Total sessions:   {total_s} across {len(avail) * HOURS} slots\n")

    print(f"  Classes sharing {worst_teacher.name}:")
    for cn, cls, req in sorted(classes_for_teacher, key=lambda x: (x[0], x[1])):
        floor, cap = get_floor_cap(cls)
        compact    = cls.grade not in NON_COMPACT
        min_days   = math.ceil(req.sessions_per_week / cap)
        print(
            f"    {cn:6s} {'[compact]' if compact else '[free]   '}  "
            f"{req.subject.name:25s}  "
            f"sessions={req.sessions_per_week}  floor={floor}  cap={cap}  "
            f"min_days_needed={min_days}"
        )

    print(f"\n  Day-by-day slot budget for {worst_teacher.name}:")
    for d in range(DAYS):
        free_h = [h for h in range(HOURS) if (d, h) not in unavail]
        demand = sum(
            req.sessions_per_week
            for cn, cls, req in classes_for_teacher
        )
        print(f"    {DAY_NAMES[d]}: {len(free_h)} slots free", end="")
        if d not in avail:
            print("  (UNAVAILABLE)")
        else:
            # How many compact-class sessions MUST land on available days?
            compact_must = sum(
                max(0, get_floor_cap(cls)[0])
                for cn, cls, req in classes_for_teacher
                if cls.grade not in NON_COMPACT
                and math.ceil(req.sessions_per_week / get_floor_cap(cls)[1]) >= (d in avail)
            )
            print(f"  (combined floor pressure: see Check 3)")

    # Show the exact combinatorial problem:
    # On each available day, how many compact classes could want a session here,
    # and what is the floor each of them needs to respect?
    print(f"\n  Combinatorial analysis:")
    print(f"  With only {len(avail)} available days ({[DAY_NAMES[d] for d in avail]}),")
    print(f"  {worst_teacher.name} must schedule {total_s} sessions.")
    print(f"  Average per available day: {total_s/max(len(avail),1):.1f}")
    print(f"  Maximum per day (8 slots): 8")
    if total_s > len(avail) * HOURS:
        print(f"\n  *** HARD INFEASIBLE: {total_s} > {len(avail) * HOURS} ***")
    else:
        print(f"\n  Raw slots are sufficient ({total_s} <= {len(avail) * HOURS}).")
        print(f"  The problem is the FLOOR constraint forcing minimum sessions")
        print(f"  per active day, combined with multiple classes sharing the")
        print(f"  same scarce days.")
        print()
        print(f"  To fix this, choose ONE of:")
        print(f"    A) Give {worst_teacher.name} more available days in the Excel sheet")
        for cn, cls, req in sorted(classes_for_teacher, key=lambda x: (x[0], x[1])):
            if cls.grade in NON_COMPACT:
                continue
            floor, cap = get_floor_cap(cls)
            print(f"    B) Lower MinDailyClassCount for {cn} (currently floor={floor})")
        print(f"    C) Redistribute sessions from {worst_teacher.name} to another teacher")

print("\n" + "=" * 76)
print("END — " + ("ISSUES FOUND — see above for fixes" if issues_found
                   else "no structural issues detected"))
print("=" * 76 + "\n")