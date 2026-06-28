"""
validate_schedule.py
====================
Validates the generated schedule against every constraint defined in the
scheduler system.

Checks performed
----------------
1.  SESSION COUNT       – every class has exactly the required sessions per
                          subject (no more, no less).
2.  NO DOUBLE-BOOKING   – a teacher is never in two places at the same time.
3.  NO ROOM CONFLICT    – a room is never used by two classes simultaneously.
4.  TEACHER AVAILABLE   – no session is placed on a slot where the teacher is
                          marked unavailable.
5.  MAX CONSECUTIVE     – no subject appears more consecutively than its limit
                          on any given day for any class.
6.  MAX DAILY CAP       – no class has more sessions on any day than its cap.
7.  MIN DAILY FLOOR     – every day a class IS scheduled (non-zero sessions)
                          has at least min_classes sessions.
8.  COMPACTNESS         – for grades 5+, every used day has no gaps (sessions
                          form a contiguous block, not necessarily from hour 0).
9.  TEACHER GAP         – no teacher has a gap larger than max_gap between
                          consecutive sessions on any day, and no more than
                          max_gaps_per_day gaps in a single day.
10. ALL SLOTS FILLED    – total sessions scheduled equals total sessions
                          required across the whole school.
"""

import sys
import pandas as pd
from collections import defaultdict

from models.subject import Subject
from models.teacher import Teacher
from models.room import Room
from models.school_class import SchoolClass, SubjectRequirement
from models.scheduled_class import ScheduledClass
from models.context import SchedulerContext
from models.schedule import Schedule
from scheduler.scheduler3 import Scheduler
from models.constraints.class_constraints import (
    MinDailyClassCount,
    MaxDailyClassCount,
)
from models.constraints.subject_constraints import MaxConsecutiveClassesConstraint
from models.constraints.teacher_constraints import (
    UnavailableTimePeriodConstraint,
    MaxTeacherGapConstraint,
)

Schedule.model_rebuild()
ScheduledClass.model_rebuild()
Teacher.model_rebuild()
Room.model_rebuild()
SchoolClass.model_rebuild()
SchedulerContext.model_rebuild()

EXCEL_PATH = "test_schedule.xlsx"
DAYS  = 5
HOURS = 8
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
NON_COMPACT_GRADES = {0, 1, 2, 3, 4}

# ── Read Excel ────────────────────────────────────────────────────────────────
teachers_df       = pd.read_excel(EXCEL_PATH, sheet_name="teachers")
classes_df        = pd.read_excel(EXCEL_PATH, sheet_name="school_schedule")
classes_limits_df = pd.read_excel(EXCEL_PATH, sheet_name="classes")

classes_limits_df.columns = classes_limits_df.columns.str.strip()
teachers_df.columns       = teachers_df.columns.str.strip()
classes_df.columns        = classes_df.columns.str.strip()

class_limits_map: dict[str, tuple[int, int]] = {}
for _, row in classes_limits_df.iterrows():
    cname = str(row["ClassName"]).strip()
    class_limits_map[cname] = (int(row["MinClasses"]), int(row["MaxClasses"]))

teacher_availability: dict[str, dict[str, int]] = {}
teacher_max_gap: dict[str, int] = {}

for _, row in teachers_df.iterrows():
    name = str(row["Teacher"]).strip()
    teacher_availability[name] = {
        day: int(row[day])
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri"]
        if day in row.index
    }
    if "MaxGap" in row.index and pd.notna(row["MaxGap"]):
        teacher_max_gap[name] = int(row["MaxGap"])
    else:
        teacher_max_gap[name] = 1

subjects_map: dict[str, Subject] = {}
teachers_map: dict[str, Teacher] = {}
rooms_map:    dict[str, Room]    = {}

for _, row in classes_df.iterrows():
    subj_name    = str(row["Subject"]).strip()
    teacher_name = str(row["Teacher"]).strip()
    class_name   = str(row["ClassName"]).strip()

    if subj_name not in subjects_map:
        subjects_map[subj_name] = Subject(name=subj_name, relevance=5)
    if teacher_name not in teachers_map:
        teachers_map[teacher_name] = Teacher(name=teacher_name, subjects=[])

    teacher = teachers_map[teacher_name]
    subject = subjects_map[subj_name]
    if subject not in teacher.subjects:
        teacher.subjects.append(subject)
    if class_name not in rooms_map:
        rooms_map[class_name] = Room(name=f"Room {class_name}")

school_classes_map: dict[str, SchoolClass] = {}

for class_name, group in classes_df.groupby("ClassName"):
    class_name = str(class_name).strip()
    room = rooms_map[class_name]
    requirements = []
    total_sessions = 0

    for _, row in group.iterrows():
        subj_name    = str(row["Subject"]).strip()
        teacher_name = str(row["Teacher"]).strip()
        sessions     = int(row["NumberOfClasses"])
        requirements.append(SubjectRequirement(
            subject=Subject(name=subj_name, relevance=5),
            teacher=teachers_map[teacher_name],
            sessions_per_week=sessions,
            room=room,
        ))
        total_sessions += sessions

    raw = class_name
    version = ""
    if raw and raw[-1].isalpha():
        version = raw[-1]
        grade_str = raw[:-1]
    else:
        grade_str = raw
    grade = int(grade_str) if grade_str.isdigit() else 0

    school_classes_map[class_name] = SchoolClass(
        grade=grade,
        version=version,
        total_class_sessions=total_sessions,
        subject_requirements=requirements,
        constraints=[],
    )

context = SchedulerContext(
    classes=list(school_classes_map.values()),
    teachers=list(teachers_map.values()),
    rooms=list(rooms_map.values()),
)

DAY_COL_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}

for teacher in context.teachers:
    avail = teacher_availability.get(teacher.name, {})
    unavailable_slots = []
    for day_col, day_idx in DAY_COL_MAP.items():
        if not avail.get(day_col, 1):
            for hour in range(HOURS):
                unavailable_slots.append((day_idx, hour))

    max_gap = teacher_max_gap.get(teacher.name, 1)
    constraints = [
        MaxTeacherGapConstraint(priority=10, teacher=teacher, max_gap=max_gap, max_gaps_per_day=1)
    ]
    if unavailable_slots:
        constraints.append(
            UnavailableTimePeriodConstraint(
                priority=10,
                teacher=teacher,
                unavailable_slots=unavailable_slots,
            )
        )
    teacher.constraints = constraints

for school_class in context.classes:
    min_classes = int(school_class.total_class_sessions / 5 - 1)
    max_classes = int(school_class.total_class_sessions / 5 + 1)

    school_class.constraints = [
        MaxDailyClassCount(priority=10, max_classes=max_classes, school_class=school_class),
        MinDailyClassCount(priority=10, min_classes=min_classes, school_class=school_class),
    ]

    for req in school_class.subject_requirements:
        spw = req.sessions_per_week
        max_consec = 2 if spw < 6 else 30
        req.subject.constraints = [
            MaxConsecutiveClassesConstraint(
                priority=10,
                subject=req.subject,
                max_classes=max_consec,
            )
        ]

# ── Solve ─────────────────────────────────────────────────────────────────────
print("Running solver...")
scheduler = Scheduler(context)
success = scheduler.solve_best(time_limit=120.0)

if not success:
    print("\n[FATAL] Solver failed to find a solution — nothing to validate.")
    sys.exit(1)

print("Solver succeeded. Running validation...\n")

# ── Validation helpers ────────────────────────────────────────────────────────
errors:   list[str] = []
warnings: list[str] = []

def err(msg: str) -> None:
    errors.append(msg)
    print(f"  [FAIL] {msg}")

def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  [WARN] {msg}")

def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")

def get_slot_teacher(slot_display: str) -> str:
    parts = slot_display.rsplit(" - ", 2)
    return parts[2].strip() if len(parts) == 3 else "?"

def get_slot_subject(slot_display: str) -> str:
    return slot_display.split(" - ")[0].strip()

# ── CHECK 1: Session counts ───────────────────────────────────────────────────
print("=" * 60)
print("CHECK 1: Session counts per subject per class")
print("=" * 60)

total_required  = 0
total_scheduled = 0

for class_name, school_class in sorted(school_classes_map.items()):
    expected: dict[str, int] = {}
    for req in school_class.subject_requirements:
        expected[req.subject.name] = req.sessions_per_week
        total_required += req.sessions_per_week

    actual: dict[str, int] = defaultdict(int)
    for day in range(DAYS):
        for hour in range(HOURS):
            slot = school_class.schedule.get_slot_display(day, hour)
            if slot:
                actual[get_slot_subject(slot)] += 1
                total_scheduled += 1

    class_ok = True
    for subj in sorted(set(expected) | set(actual)):
        exp = expected.get(subj, 0)
        act = actual.get(subj, 0)
        if exp != act:
            err(f"{class_name} | {subj}: expected {exp}, got {act}")
            class_ok = False

    if class_ok:
        ok(f"{class_name}: all {sum(expected.values())} sessions correctly placed")

print()

# ── CHECK 2: No teacher double-booking ───────────────────────────────────────
print("=" * 60)
print("CHECK 2: Teacher double-booking")
print("=" * 60)

teacher_slots: dict[str, dict[tuple[int, int], list[str]]] = defaultdict(lambda: defaultdict(list))

for class_name, school_class in school_classes_map.items():
    for day in range(DAYS):
        for hour in range(HOURS):
            slot = school_class.schedule.get_slot_display(day, hour)
            if slot:
                teacher_slots[get_slot_teacher(slot)][(day, hour)].append(
                    f"{class_name}/{get_slot_subject(slot)}"
                )

double_booked = False
for teacher_name, slots in sorted(teacher_slots.items()):
    for (day, hour), classes in sorted(slots.items()):
        if len(classes) > 1:
            double_booked = True
            err(f"{teacher_name} double-booked {DAY_NAMES[day]} H{hour+1}: {', '.join(classes)}")

if not double_booked:
    ok(f"No teacher double-bookings across {len(teacher_slots)} teachers")

print()

# ── CHECK 3: No room conflicts ────────────────────────────────────────────────
print("=" * 60)
print("CHECK 3: Room conflicts")
print("=" * 60)

room_slots: dict[str, dict[tuple[int, int], list[str]]] = defaultdict(lambda: defaultdict(list))

for class_name, school_class in school_classes_map.items():
    for day in range(DAYS):
        for hour in range(HOURS):
            if school_class.schedule.get_slot_display(day, hour):
                room_slots[f"Room {class_name}"][(day, hour)].append(class_name)

room_conflicts = False
for room_name, slots in sorted(room_slots.items()):
    for (day, hour), classes in sorted(slots.items()):
        if len(classes) > 1:
            room_conflicts = True
            err(f"{room_name} conflict {DAY_NAMES[day]} H{hour+1}: {', '.join(classes)}")

if not room_conflicts:
    ok(f"No room conflicts across {len(room_slots)} rooms")

print()

# ── CHECK 4: Teacher availability ────────────────────────────────────────────
print("=" * 60)
print("CHECK 4: Teacher availability")
print("=" * 60)

teacher_unavail: dict[str, set[tuple[int, int]]] = {}
for teacher in context.teachers:
    unavail: set[tuple[int, int]] = set()
    for c in teacher.constraints:
        if isinstance(c, UnavailableTimePeriodConstraint):
            unavail = c._unavailable_set
            break
    teacher_unavail[teacher.name] = unavail

avail_violations = False
for class_name, school_class in sorted(school_classes_map.items()):
    for day in range(DAYS):
        for hour in range(HOURS):
            slot = school_class.schedule.get_slot_display(day, hour)
            if not slot:
                continue
            tname = get_slot_teacher(slot)
            if (day, hour) in teacher_unavail.get(tname, set()):
                avail_violations = True
                err(f"{class_name} | {get_slot_subject(slot)}: {tname} unavailable {DAY_NAMES[day]} H{hour+1}")

if not avail_violations:
    ok("No sessions placed on teacher-unavailable slots")

print()

# ── CHECK 5: Max consecutive classes per subject ──────────────────────────────
print("=" * 60)
print("CHECK 5: Max consecutive classes per subject")
print("=" * 60)

consec_violations = False
for class_name, school_class in sorted(school_classes_map.items()):
    max_consec_map: dict[str, int] = {}
    for req in school_class.subject_requirements:
        for c in req.subject.constraints:
            if isinstance(c, MaxConsecutiveClassesConstraint):
                max_consec_map[req.subject.name] = c.max_classes

    for day in range(DAYS):
        day_slots = [
            (hour, get_slot_subject(school_class.schedule.get_slot_display(day, hour)))
            for hour in range(HOURS)
            if school_class.schedule.get_slot_display(day, hour)
        ]
        if not day_slots:
            continue

        run_subj, run_len = day_slots[0][1], 1
        for i in range(1, len(day_slots)):
            hour, subj = day_slots[i]
            prev_hour  = day_slots[i - 1][0]
            if subj == run_subj and hour == prev_hour + 1:
                run_len += 1
            else:
                limit = max_consec_map.get(run_subj, 30)
                if run_len > limit:
                    consec_violations = True
                    err(f"{class_name} | {run_subj} {DAY_NAMES[day]}: {run_len} consecutive (limit {limit})")
                run_subj, run_len = subj, 1

        limit = max_consec_map.get(run_subj, 30)
        if run_len > limit:
            consec_violations = True
            err(f"{class_name} | {run_subj} {DAY_NAMES[day]}: {run_len} consecutive (limit {limit})")

if not consec_violations:
    ok("No max-consecutive violations")

print()

# ── CHECK 6: Max daily class count ────────────────────────────────────────────
print("=" * 60)
print("CHECK 6: Max daily class count")
print("=" * 60)

max_cap_violations = False
for class_name, school_class in sorted(school_classes_map.items()):
    max_classes = int(school_class.total_class_sessions / 5 + 1)
    for day in range(DAYS):
        count = sum(
            1 for hour in range(HOURS)
            if school_class.schedule.get_slot_display(day, hour)
        )
        if count > max_classes:
            max_cap_violations = True
            err(f"{class_name} {DAY_NAMES[day]}: {count} sessions exceeds cap {max_classes}")

if not max_cap_violations:
    ok("No max-daily-cap violations")

print()

# ── CHECK 7: Min daily class count ───────────────────────────────────────────
print("=" * 60)
print("CHECK 7: Min daily class count (non-zero days only)")
print("=" * 60)

min_floor_violations = False
for class_name, school_class in sorted(school_classes_map.items()):
    min_classes = int(school_class.total_class_sessions / 5 - 1)
    if min_classes <= 0:
        continue
    for day in range(DAYS):
        count = sum(
            1 for hour in range(HOURS)
            if school_class.schedule.get_slot_display(day, hour)
        )
        if 0 < count < min_classes:
            min_floor_violations = True
            err(f"{class_name} {DAY_NAMES[day]}: {count} session(s) below floor {min_classes}")

if not min_floor_violations:
    ok("No min-daily-floor violations")

print()

# ── CHECK 8: Compactness (grades 5+) ─────────────────────────────────────────
print("=" * 60)
print("CHECK 8: Schedule compactness (grades 5+, contiguous block per day)")
print("=" * 60)

compact_violations = False
for class_name, school_class in sorted(school_classes_map.items()):
    if school_class.grade in NON_COMPACT_GRADES:
        continue

    for day in range(DAYS):
        slots_used = [
            hour for hour in range(HOURS)
            if school_class.schedule.get_slot_display(day, hour)
        ]
        if not slots_used:
            continue

        for i in range(1, len(slots_used)):
            if slots_used[i] != slots_used[i - 1] + 1:
                compact_violations = True
                err(
                    f"{class_name} {DAY_NAMES[day]}: gap between "
                    f"H{slots_used[i-1]+1} and H{slots_used[i]+1}"
                )
                break

if not compact_violations:
    ok("All compact-grade schedules have no intra-day gaps")

print()

# ── CHECK 9: Teacher gap constraint ──────────────────────────────────────────
print("=" * 60)
print("CHECK 9: Teacher gap constraint")
print("=" * 60)

# Build per-teacher per-day session lists from the schedule
teacher_day_sessions: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))

for class_name, school_class in school_classes_map.items():
    for day in range(DAYS):
        for hour in range(HOURS):
            slot = school_class.schedule.get_slot_display(day, hour)
            if slot:
                teacher_day_sessions[get_slot_teacher(slot)][day].append(hour)

gap_violations = False
for teacher in context.teachers:
    max_gap = teacher_max_gap.get(teacher.name, 1)
    day_sessions = teacher_day_sessions.get(teacher.name, {})

    for day in range(DAYS):
        placed = sorted(day_sessions.get(day, []))
        if len(placed) < 2:
            continue

        gaps_found = 0
        for i in range(1, len(placed)):
            gap_size = placed[i] - placed[i - 1] - 1
            if gap_size > max_gap:
                gap_violations = True
                err(
                    f"{teacher.name} {DAY_NAMES[day]}: gap of {gap_size} free hour(s) "
                    f"between H{placed[i-1]+1} and H{placed[i]+1} (max_gap={max_gap})"
                )
            if gap_size > 0:
                gaps_found += 1

        if gaps_found > 1:
            gap_violations = True
            err(
                f"{teacher.name} {DAY_NAMES[day]}: {gaps_found} gaps in one day "
                f"(max_gaps_per_day=1), sessions at {[h+1 for h in placed]}"
            )

if not gap_violations:
    ok("No teacher gap violations")

print()

# ── CHECK 10: Global totals ───────────────────────────────────────────────────
print("=" * 60)
print("CHECK 10: Global session totals")
print("=" * 60)

if total_required == total_scheduled:
    ok(f"Total sessions: required={total_required}, scheduled={total_scheduled}")
else:
    err(f"Total sessions mismatch: required={total_required}, scheduled={total_scheduled}")

print()

# ── Summary ───────────────────────────────────────────────────────────────────
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Errors   : {len(errors)}")
print(f"  Warnings : {len(warnings)}")

if errors:
    print("\nFailed checks:")
    for e in errors:
        print(f"  • {e}")
    print("\n[RESULT] Schedule is INVALID.")
    sys.exit(1)
else:
    print("\n[RESULT] Schedule is VALID — all constraints satisfied.")
    sys.exit(0)