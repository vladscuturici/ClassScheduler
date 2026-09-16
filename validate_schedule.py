#!/usr/bin/env python3
"""
validate_schedule.py — sanity-checks a saved CLASS_SCHEDULER project file.

Usage:
    python validate_schedule.py project.json
    python validate_schedule.py project.json --verbose   # also print OK checks

What it checks
---------------
Given the JSON produced by the frontend's saveProjectFile() — which contains
`classes`, `teachers`, and `grids` (class_schedules + teacher_schedules) — this
script re-derives every hard constraint the solver is supposed to guarantee
and reports any mismatch:

  1. Every class in `classes` has an entry in grids.class_schedules, and vice versa.
  2. Every teacher in `teachers` has an entry in grids.teacher_schedules.
  3. Session counts: each subject is scheduled exactly `sessions_per_week` times
     for its class (not more, not less).
  4. No teacher is double-booked: at most one lesson per teacher per (day, hour).
  5. class_schedules and teacher_schedules agree with each other (every lesson
     visible from the class side is visible from the teacher side, same subject/
     teacher/class, and nothing extra on either side).
  6. Teacher day-availability is respected (a teacher with a day marked
     unavailable, or an explicit unavailable_slot, never appears there).
  7. Same-subject contiguity: within one class/day, all sessions of the same
     subject form a single unbroken block (no split blocks like H1 and H4).
  8. Max-consecutive-length: that block doesn't exceed the subject's
     max_consecutive (explicit override, else the 1/<3, 2/<6, unlimited/>=6
     default used by the backend).
  9. Compactness (grades 5+ only — grades 0-4 are exempt by design): each
     active day's lessons occupy hours 0..k-1 with no gaps.
 10. MinDailyClassCount / MaxDailyClassCount respected per class per active day.

Exit code is 0 if everything passes, 1 if any check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

DAYS = 5
HOURS = 8
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
LOW_GRADE_MAX = 4  # grades <= this are exempt from compactness (mirrors api.py)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def class_grade(name: str) -> int:
    """Mirrors _build_context's grade parsing in api.py:
    trailing letter = version, remaining numeric prefix = grade, 'P*' = grade 0.
    """
    s = str(name).strip()
    if not s:
        return 0
    if s[-1].isalpha():
        grade_str = s[:-1]
    else:
        grade_str = s
    return int(grade_str) if grade_str.isdigit() else 0


def default_max_consecutive(sessions_per_week: int) -> int:
    if sessions_per_week < 3:
        return 1
    if sessions_per_week < 6:
        return 2
    return 30  # effectively unlimited


class Report:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.failures: list[str] = []
        self.oks: list[str] = []

    def fail(self, msg: str):
        self.failures.append(msg)

    def ok(self, msg: str):
        self.oks.append(msg)

    def print(self):
        if self.verbose:
            for m in self.oks:
                print(f"  \u2713 {m}")
        print()
        if self.failures:
            print(f"\u2717 {len(self.failures)} problem(s) found:\n")
            for m in self.failures:
                print(f"  \u2717 {m}")
        else:
            print("\u2713 All checks passed — schedule looks internally consistent.")


# ─────────────────────────────────────────────────────────────────────────────
# main validation
# ─────────────────────────────────────────────────────────────────────────────

def validate(project: dict, report: Report) -> None:
    classes = project.get("classes", [])
    teachers = project.get("teachers", [])
    grids = project.get("grids", {})
    class_schedules = grids.get("class_schedules", {})
    teacher_schedules = grids.get("teacher_schedules", {})

    class_by_name = {c["name"]: c for c in classes}
    teacher_by_name = {t["name"]: t for t in teachers}

    # ── 1/2. presence checks ────────────────────────────────────────────────
    missing_grid_for_class = set(class_by_name) - set(class_schedules)
    extra_grid_for_class = set(class_schedules) - set(class_by_name)
    if missing_grid_for_class:
        report.fail(f"Classes with no schedule grid at all: {sorted(missing_grid_for_class)}")
    else:
        report.ok("Every declared class has a schedule grid.")
    if extra_grid_for_class:
        report.fail(f"Schedule grid has classes not in the class list: {sorted(extra_grid_for_class)}")

    missing_grid_for_teacher = set(teacher_by_name) - set(teacher_schedules)
    extra_grid_for_teacher = set(teacher_schedules) - set(teacher_by_name)
    if missing_grid_for_teacher:
        report.fail(f"Teachers with no schedule grid at all: {sorted(missing_grid_for_teacher)}")
    else:
        report.ok("Every declared teacher has a schedule grid.")
    if extra_grid_for_teacher:
        report.fail(f"Schedule grid has teachers not in the teacher list: {sorted(extra_grid_for_teacher)}")

    # ── build a normalized view of the class grids ──────────────────────────
    # class_slots[class_name][(day,hour)] = {"subject":..., "teacher":...} | None
    class_slots: dict[str, dict[tuple[int, int], dict | None]] = {}
    for cname, grid in class_schedules.items():
        slots = {}
        for d in range(min(DAYS, len(grid))):
            for h in range(min(HOURS, len(grid[d]))):
                slots[(d, h)] = grid[d][h]
        class_slots[cname] = slots

    teacher_slots: dict[str, dict[tuple[int, int], dict | None]] = {}
    for tname, grid in teacher_schedules.items():
        slots = {}
        for d in range(min(DAYS, len(grid))):
            for h in range(min(HOURS, len(grid[d]))):
                slots[(d, h)] = grid[d][h]
        teacher_slots[tname] = slots

    # ── 3. session counts per (class, subject) ──────────────────────────────
    for cname, cinfo in class_by_name.items():
        if cname not in class_slots:
            continue  # already reported above
        slots = class_slots[cname]
        actual_counts = defaultdict(int)
        for slot in slots.values():
            if slot:
                actual_counts[slot["subject"]] += 1

        expected_counts = defaultdict(int)
        for subj in cinfo.get("subjects", []):
            expected_counts[subj["name"]] += subj["sessions_per_week"]

        all_subjects = set(actual_counts) | set(expected_counts)
        for subj_name in sorted(all_subjects):
            exp = expected_counts.get(subj_name, 0)
            act = actual_counts.get(subj_name, 0)
            if exp != act:
                report.fail(
                    f"Class {cname} / {subj_name}: expected {exp} session(s)/week, "
                    f"schedule has {act}."
                )
        if all(expected_counts.get(s, 0) == actual_counts.get(s, 0) for s in all_subjects):
            report.ok(f"Class {cname}: all subject session counts match.")

    # ── 4. teacher double-booking (within teacher_schedules itself) ─────────
    # Structurally a dict keyed by (day,hour) can't hold two lessons at once,
    # so this only catches a malformed/hand-edited file with duplicate day/hour
    # entries in a list-of-lessons format — included for robustness. With the
    # grid format this check is effectively guaranteed, but we verify shape.
    for tname, grid in teacher_schedules.items():
        if len(grid) != DAYS or any(len(day_row) != HOURS for day_row in grid):
            report.fail(f"Teacher {tname}: schedule grid has wrong dimensions (expected {DAYS}x{HOURS}).")

    # ── 5. class_schedules vs teacher_schedules cross-consistency ───────────
    mismatches = 0
    for cname, slots in class_slots.items():
        for (d, h), slot in slots.items():
            if slot is None:
                continue
            tname = slot["teacher"]
            subj = slot["subject"]
            t_slot = teacher_slots.get(tname, {}).get((d, h))
            if t_slot is None:
                report.fail(
                    f"{cname} {DAY_NAMES[d]} H{h+1}: class grid shows {subj}({tname}), "
                    f"but {tname}'s own schedule shows nothing there."
                )
                mismatches += 1
            elif t_slot.get("class_name") != cname or t_slot.get("subject") != subj:
                report.fail(
                    f"{cname} {DAY_NAMES[d]} H{h+1}: class grid shows {subj}({tname}), "
                    f"but {tname}'s schedule shows {t_slot.get('subject')} for "
                    f"{t_slot.get('class_name')} instead."
                )
                mismatches += 1

    # reverse direction: every teacher lesson must be visible from the class side
    for tname, slots in teacher_slots.items():
        for (d, h), slot in slots.items():
            if slot is None:
                continue
            cname = slot["class_name"]
            subj = slot["subject"]
            c_slot = class_slots.get(cname, {}).get((d, h))
            if c_slot is None:
                report.fail(
                    f"{tname} {DAY_NAMES[d]} H{h+1}: teacher grid shows {subj} for {cname}, "
                    f"but {cname}'s own schedule shows nothing there."
                )
                mismatches += 1
            elif c_slot.get("teacher") != tname or c_slot.get("subject") != subj:
                report.fail(
                    f"{tname} {DAY_NAMES[d]} H{h+1}: teacher grid shows {subj} for {cname}, "
                    f"but {cname}'s schedule shows {c_slot.get('subject')}/{c_slot.get('teacher')} instead."
                )
                mismatches += 1

    if mismatches == 0:
        report.ok("class_schedules and teacher_schedules are fully consistent with each other.")

    # ── 6. teacher availability respected ────────────────────────────────────
    DAY_COL = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    for tname, tinfo in teacher_by_name.items():
        slots = teacher_slots.get(tname, {})
        avail = tinfo.get("availability", {})
        unavailable_slots = {tuple(s) for s in tinfo.get("unavailable_slots", [])}

        bad = []
        for (d, h), slot in slots.items():
            if slot is None:
                continue
            day_key = DAY_COL[d] if d < len(DAY_COL) else None
            day_available = avail.get(day_key, HOURS) if day_key else HOURS
            day_blocked = (not unavailable_slots) and (not day_available)
            explicit_blocked = (d, h) in unavailable_slots
            if day_blocked or explicit_blocked:
                bad.append(f"{DAY_NAMES[d]} H{h+1}")
        if bad:
            report.fail(f"Teacher {tname} is scheduled during declared unavailable time: {', '.join(bad)}")
        else:
            report.ok(f"Teacher {tname}: no lessons during unavailable time.")

    # ── 7 & 8. same-subject contiguity + max-consecutive length ─────────────
    for cname, cinfo in class_by_name.items():
        slots = class_slots.get(cname)
        if not slots:
            continue

        # build per-subject max_consecutive lookup for this class
        mc_map: dict[str, int] = {}
        for subj in cinfo.get("subjects", []):
            mc = subj.get("max_consecutive")
            if mc is None:
                mc = default_max_consecutive(subj["sessions_per_week"])
            mc_map[subj["name"]] = mc

        for d in range(DAYS):
            day_slots = [slots.get((d, h)) for h in range(HOURS)]
            by_subject: dict[str, list[int]] = defaultdict(list)
            for h, s in enumerate(day_slots):
                if s:
                    by_subject[s["subject"]].append(h)

            for subj_name, hours in by_subject.items():
                if len(hours) < 2:
                    continue
                hours.sort()
                # contiguity
                runs = 1
                for i in range(1, len(hours)):
                    if hours[i] != hours[i - 1] + 1:
                        runs += 1
                if runs > 1:
                    report.fail(
                        f"Class {cname} {DAY_NAMES[d]}: {subj_name} is split into "
                        f"{runs} separate blocks at hours {[h+1 for h in hours]} "
                        f"(must be one contiguous block)."
                    )
                # length cap
                mc = mc_map.get(subj_name, 30)
                if mc < HOURS and len(hours) > mc:
                    report.fail(
                        f"Class {cname} {DAY_NAMES[d]}: {subj_name} runs {len(hours)} "
                        f"consecutive hours, exceeding its max_consecutive={mc}."
                    )

    # ── 9. compactness (grades 5+) ────────────────────────────────────────────
    for cname, slots in class_slots.items():
        grade = class_grade(cname)
        if grade <= LOW_GRADE_MAX:
            continue  # exempt by design
        for d in range(DAYS):
            occupied = [h for h in range(HOURS) if slots.get((d, h))]
            if not occupied:
                continue
            occupied.sort()
            if occupied[0] != 0:
                report.fail(
                    f"Class {cname} {DAY_NAMES[d]}: first lesson is at H{occupied[0]+1}, "
                    f"not H1 (compactness requires starting at H1)."
                )
                continue
            expected = list(range(len(occupied)))
            if occupied != expected:
                report.fail(
                    f"Class {cname} {DAY_NAMES[d]}: lessons at hours "
                    f"{[h+1 for h in occupied]} have a gap (compactness violated)."
                )

    # ── 10. min/max daily class count ────────────────────────────────────────
    for cname, cinfo in class_by_name.items():
        slots = class_slots.get(cname)
        if not slots:
            continue
        min_daily = cinfo.get("min_daily", 0)
        max_daily = cinfo.get("max_daily", HOURS)
        for d in range(DAYS):
            count = sum(1 for h in range(HOURS) if slots.get((d, h)))
            if count == 0:
                continue  # an inactive day is not subject to the floor
            if count < min_daily:
                report.fail(
                    f"Class {cname} {DAY_NAMES[d]}: only {count} session(s), "
                    f"below min_daily={min_daily}."
                )
            if count > max_daily:
                report.fail(
                    f"Class {cname} {DAY_NAMES[d]}: {count} session(s), "
                    f"above max_daily={max_daily}."
                )


def main():
    ap = argparse.ArgumentParser(description="Validate a saved class-scheduler project file.")
    ap.add_argument("project_file", help="Path to the saved project .json file")
    ap.add_argument("--verbose", "-v", action="store_true", help="Also print passing checks")
    args = ap.parse_args()

    with open(args.project_file, encoding="utf-8") as f:
        project = json.load(f)

    report = Report(verbose=args.verbose)
    validate(project, report)
    report.print()

    sys.exit(1 if report.failures else 0)


if __name__ == "__main__":
    main()