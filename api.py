"""
api.py  —  FastAPI backend for CLASS_SCHEDULER
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from pydantic import BaseModel

from models.subject import Subject
from models.teacher import Teacher
from models.room import Room
from models.school_class import SchoolClass, SubjectRequirement
from models.scheduled_class import ScheduledClass
from models.context import SchedulerContext
from models.schedule import Schedule
from scheduler.scheduler_cpsat import Scheduler
from models.constraints.class_constraints import (
    MinDailyClassCount,
    MaxDailyClassCount,
    BalancedDailyDifficultyConstraint,
)
from models.constraints.subject_constraints import MaxConsecutiveClassesConstraint
from models.constraints.teacher_constraints import (
    UnavailableTimePeriodConstraint,
    MaxTeacherGapConstraint,
)

Schedule.model_rebuild()
ScheduledClass.model_rebuild()
Teacher.model_rebuild()
from models.room import Room as _R; _R.model_rebuild()
SchoolClass.model_rebuild()
SchedulerContext.model_rebuild()

DAYS      = 5
HOURS     = 8
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY_COL_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
DAY_SHORT   = ["Mon", "Tue", "Wed", "Thu", "Fri"]

DAYS      = 5
HOURS     = 8
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY_NAMES_RO = ["Luni", "Marti", "Miercuri", "Joi", "Vineri"]
DAY_COL_MAP = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}
DAY_SHORT   = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# H1 = 8:00, H2 = 9:00, etc. Adjust if the school day starts at a different hour.
START_HOUR = 8
def _hour_label(h: int) -> str:
    return f"{START_HOUR + h}:00"

# Grades at or below this are treated as "low grade" — their schedules are
# opportunistic slots filled in as teacher availability allows, not a
# finalized fixed-start schedule, so late-start / compactness checks that
# make sense for grade 5+ don't apply to them yet.
LOW_GRADE_MAX = 4

_session: dict[str, Any] = {}

app = FastAPI(title="Class Scheduler API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class TeacherAvailability(BaseModel):
    Mon: int = HOURS
    Tue: int = HOURS
    Wed: int = HOURS
    Thu: int = HOURS
    Fri: int = HOURS


class SubjectInfo(BaseModel):
    name: str
    sessions_per_week: int
    teacher: str
    relevance: int = 5
    max_consecutive: Optional[int] = None


class ClassInfo(BaseModel):
    name: str
    min_daily: int
    max_daily: int
    subjects: list[SubjectInfo]


class TeacherInfo(BaseModel):
    name: str
    availability: TeacherAvailability
    unavailable_slots: list[list[int]] = []
    max_gap: int = 2 


class ParsedData(BaseModel):
    session_id: str
    classes: list[ClassInfo]
    teachers: list[TeacherInfo]


class SolveRequest(BaseModel):
    session_id: str
    classes: list[ClassInfo]
    teachers: list[TeacherInfo]
    max_solutions: int = 1
    use_balanced_difficulty: bool = False


class SlotInfo(BaseModel):
    subject: str
    teacher: str
    class_name: str


class TeacherSlotInfo(BaseModel):
    class_name: str
    subject: str

class ScheduleGrid(BaseModel):
    class_schedules:   dict[str, list[list[Optional[SlotInfo]]]]
    teacher_schedules: dict[str, list[list[Optional[TeacherSlotInfo]]]]


class RestoreSessionRequest(BaseModel):
    """Rebuilds a backend session from a previously-exported project file,
    without re-running the solver. `grids` holds the exact slot placement
    that was saved, which we replay directly onto a freshly built context."""
    classes:  list[ClassInfo]
    teachers: list[TeacherInfo]
    grids:    ScheduleGrid


class RestoreSessionResponse(BaseModel):
    session_id: str
    classes:    list[ClassInfo]
    teachers:   list[TeacherInfo]
    grids:      ScheduleGrid


class SwapRequest(BaseModel):
    session_id: str
    class_name_a: str
    day_a: int
    hour_a: int
    class_name_b: str
    day_b: int
    hour_b: int


class SwapCandidatesRequest(BaseModel):
    session_id: str
    class_name: str
    day: int
    hour: int


class SwapCandidate(BaseModel):
    class_name: str
    day: int
    hour: int
    status: str
    violated_constraints: list[str]

class ManualSlot(BaseModel):
    class_name: str
    subject: str
    teacher: str
    day: int
    hour: int

class InitManualRequest(BaseModel):
    session_id: str
    classes: list[ClassInfo]
    teachers: list[TeacherInfo]

class ManualPlaceRequest(BaseModel):
    session_id: str
    class_name: str
    subject: str
    teacher: str
    day: int
    hour: int

class ManualClearRequest(BaseModel):
    session_id: str
    day: int
    hour: int
    teacher: str 
# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_excel(data: bytes) -> ParsedData:
    buf = io.BytesIO(data)
    teachers_df       = pd.read_excel(buf, sheet_name="teachers");       buf.seek(0)
    classes_df        = pd.read_excel(buf, sheet_name="school_schedule"); buf.seek(0)
    classes_limits_df = pd.read_excel(buf, sheet_name="classes")

    teachers_df.columns       = teachers_df.columns.str.strip()
    classes_df.columns        = classes_df.columns.str.strip()
    classes_limits_df.columns = classes_limits_df.columns.str.strip()

    class_limits_map: dict[str, tuple[int, int]] = {}
    for _, row in classes_limits_df.iterrows():
        cname = str(row["ClassName"]).strip()
        class_limits_map[cname] = (int(row["MinClasses"]), int(row["MaxClasses"]))

    teacher_avail_raw: dict[str, dict[str, int]] = {}
    for _, row in teachers_df.iterrows():
        name = str(row["Teacher"]).strip()
        teacher_avail_raw[name] = {d: int(row[d]) for d in DAY_SHORT if d in row.index}

    classes_out: list[ClassInfo] = []
    for class_name, group in classes_df.groupby("ClassName"):
        class_name = str(class_name).strip()
        subjects_out: list[SubjectInfo] = []
        total = 0
        for _, row in group.iterrows():
            sessions = int(row["NumberOfClasses"])
            total += sessions
            subjects_out.append(SubjectInfo(
                name=str(row["Subject"]).strip(),
                sessions_per_week=sessions,
                teacher=str(row["Teacher"]).strip(),
                relevance=5,
            ))
        if class_name in class_limits_map:
            mn, mx = class_limits_map[class_name]
        else:
            mn = max(1, int(total / 5 - 1))
            mx = int(total / 5 + 1)
        classes_out.append(ClassInfo(name=class_name, min_daily=mn, max_daily=mx, subjects=subjects_out))

    teachers_out: list[TeacherInfo] = []
    for name, avail in teacher_avail_raw.items():
        teachers_out.append(TeacherInfo(
            name=name,
            availability=TeacherAvailability(
                Mon=avail.get("Mon", HOURS), Tue=avail.get("Tue", HOURS),
                Wed=avail.get("Wed", HOURS), Thu=avail.get("Thu", HOURS),
                Fri=avail.get("Fri", HOURS),
            ),
        ))

    session_id = str(uuid.uuid4())
    _session[session_id] = {"excel_bytes": data}
    return ParsedData(session_id=session_id, classes=classes_out, teachers=teachers_out)


def _build_context(req: SolveRequest) -> tuple[SchedulerContext, dict, dict]:
    teachers_map:       dict[str, Teacher]    = {}
    rooms_map:          dict[str, Room]       = {}
    school_classes_map: dict[str, SchoolClass] = {}

    for t in req.teachers:
        teachers_map[t.name] = Teacher(name=t.name, subjects=[])

    for ci in req.classes:
        if ci.name not in rooms_map:
            rooms_map[ci.name] = Room(name=f"Room {ci.name}")
        room = rooms_map[ci.name]
        requirements = []
        total = 0
        for si in ci.subjects:
            subj = Subject(name=si.name, relevance=si.relevance)
            teacher = teachers_map[si.teacher]
            if subj.name not in [s.name for s in teacher.subjects]:
                teacher.subjects.append(subj)
            requirements.append(SubjectRequirement(
                subject=subj, teacher=teacher,
                sessions_per_week=si.sessions_per_week, room=room,
            ))
            total += si.sessions_per_week

        raw = ci.name
        version = ""
        if raw and raw[-1].isalpha():
            version   = raw[-1]
            grade_str = raw[:-1]
        else:
            grade_str = raw
        grade = int(grade_str) if grade_str.isdigit() else 0

        school_classes_map[ci.name] = SchoolClass(
            grade=grade, version=version,
            total_class_sessions=total,
            subject_requirements=requirements,
            constraints=[],
        )

    context = SchedulerContext(
        classes=list(school_classes_map.values()),
        teachers=list(teachers_map.values()),
        rooms=list(rooms_map.values()),
    )

    for teacher in context.teachers:
        t_info = next((t for t in req.teachers if t.name == teacher.name), None)
        unavailable_slots = []
        if t_info and t_info.unavailable_slots:
            unavailable_slots = [tuple(s) for s in t_info.unavailable_slots]
        elif t_info:
            avail = t_info.availability.model_dump()
            for day_col, day_idx in DAY_COL_MAP.items():
                if not avail.get(day_col, HOURS):
                    for hour in range(HOURS):
                        unavailable_slots.append((day_idx, hour))

        max_gap = t_info.max_gap if t_info else 2
        constraints = [
            MaxTeacherGapConstraint(
                priority=10,
                teacher=teacher,
                max_gap=max_gap,
                max_gaps_per_day=1,
            )
        ]
        if unavailable_slots:
            constraints.append(UnavailableTimePeriodConstraint(
                priority=10,
                teacher=teacher,
                unavailable_slots=unavailable_slots,
            ))
        teacher.constraints = constraints

    for ci_info in req.classes:
        sc = school_classes_map[ci_info.name]
        sc.constraints = [
            MaxDailyClassCount(priority=10, max_classes=ci_info.max_daily, school_class=sc),
            MinDailyClassCount(priority=10, min_classes=ci_info.min_daily, school_class=sc),
        ]
        if req.use_balanced_difficulty:
            sc.constraints.append(BalancedDailyDifficultyConstraint(priority=7, school_class=sc))
        for req_obj, si in zip(sc.subject_requirements, ci_info.subjects):
            mc = si.max_consecutive if si.max_consecutive is not None else (
                1 if si.sessions_per_week < 3 else (2 if si.sessions_per_week < 6 else 30)
            )
            req_obj.subject.constraints = [MaxConsecutiveClassesConstraint(
                priority=10, subject=req_obj.subject, max_classes=mc,
            )]

    return context, school_classes_map, teachers_map


def _extract_grids(
    school_classes_map: dict[str, SchoolClass],
    teachers_map: dict[str, Teacher],
) -> ScheduleGrid:
    class_schedules: dict[str, list[list[Optional[SlotInfo]]]] = {}
    for class_name, sc in school_classes_map.items():
        grid = [[None] * HOURS for _ in range(DAYS)]
        for (day, hour), slot in sc.schedule.slots.items():
            if slot is not None and 0 <= day < DAYS and 0 <= hour < HOURS:
                grid[day][hour] = SlotInfo(
                    subject=slot.subject.name,
                    teacher=slot.teacher.name,
                    class_name=class_name,
                )
        class_schedules[class_name] = grid

    teacher_schedules: dict[str, list[list[Optional[TeacherSlotInfo]]]] = {
        tname: [[None] * HOURS for _ in range(DAYS)]
        for tname in teachers_map
    }
    for class_name, sc in school_classes_map.items():
        for (day, hour), slot in sc.schedule.slots.items():
            if slot is not None and 0 <= day < DAYS and 0 <= hour < HOURS:
                tname = slot.teacher.name
                if tname in teacher_schedules:
                    teacher_schedules[tname][day][hour] = TeacherSlotInfo(
                        class_name=class_name,
                        subject=slot.subject.name,
                    )

    return ScheduleGrid(class_schedules=class_schedules, teacher_schedules=teacher_schedules)

def _compute_export_hours(hour_indices) -> int:
    """Given an iterable of hour indices actually used, return how many hour
    columns/rows to export — trailing unused hours (e.g. H8 / 15:00) are
    dropped. Falls back to the full HOURS if nothing is used at all."""
    used = list(hour_indices)
    if not used:
        return HOURS
    return min(HOURS, max(used) + 1)

def _build_excel_bytes(
    school_classes_map: dict[str, SchoolClass],
    teachers_map: dict[str, Teacher],
) -> tuple[bytes, bytes]:
    HEADER_FILL  = PatternFill("solid", fgColor="2F5496")
    DAY_FILL     = PatternFill("solid", fgColor="4472C4")
    TEACHER_FILL = PatternFill("solid", fgColor="D9E1F2")
    CLASS_FILL   = PatternFill("solid", fgColor="E2EFDA")
    EMPTY_FILL   = PatternFill("solid", fgColor="F2F2F2")
    WHITE_BOLD   = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    DARK_BOLD    = Font(name="Arial", bold=True, color="1F3864", size=10)
    CLASS_FONT   = Font(name="Arial", bold=True, color="375623", size=10)
    CENTER       = Alignment(horizontal="center", vertical="center", wrap_text=True)
    LEFT         = Alignment(horizontal="left", vertical="center")
    thin         = Side(style="thin", color="BFBFBF")
    thick        = Side(style="medium", color="404040")
    BORDER       = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ── one global export_hours for the whole export ─────────────────────────
    # Only drop hour index 7 (H8 / 15:00) if it is NEVER used by ANY class,
    # ANY teacher, ANYWHERE. Otherwise every sheet keeps all 8 hours.
    last_hour_used = 0
    for sc in school_classes_map.values():
        for (day, hour), slot in sc.schedule.slots.items():
            if slot is not None:
                last_hour_used = max(last_hour_used, hour)
    export_hours = min(HOURS, last_hour_used + 1)

    teacher_grid: dict[str, dict[tuple[int, int], str]] = {t: {} for t in teachers_map}
    for class_name, sc in school_classes_map.items():
        for (day, hour), slot in sc.schedule.slots.items():
            if slot is not None and slot.teacher.name in teacher_grid:
                teacher_grid[slot.teacher.name][(day, hour)] = class_name

    # ── helper to draw the "all teachers" overview sheet ─────────────────────
    # This is the ONLY sheet that gets the thick day-separator borders.
    def _draw_overview_sheet(ws, row_names, cell_lookup, totals):
        ws.cell(1, 1, "Profesor").font = WHITE_BOLD
        ws.cell(1, 1).fill = HEADER_FILL; ws.cell(1, 1).alignment = CENTER; ws.cell(1, 1).border = BORDER
        ws.cell(1, 2, "Total").font = WHITE_BOLD; ws.cell(1, 2).fill = HEADER_FILL
        ws.cell(1, 2).alignment = CENTER; ws.cell(1, 2).border = BORDER
        for di, dn in enumerate(DAY_NAMES_RO):
            sc_col = 3 + di * export_hours; ec = sc_col + export_hours - 1
            ws.merge_cells(start_row=1, start_column=sc_col, end_row=1, end_column=ec)
            cell = ws.cell(1, sc_col, dn)
            cell.font = WHITE_BOLD; cell.fill = DAY_FILL; cell.alignment = CENTER
            cell.border = Border(left=thick, right=thin, top=thin, bottom=thin)
        ws.cell(2, 1).fill = HEADER_FILL; ws.cell(2, 1).border = BORDER
        ws.cell(2, 2).fill = HEADER_FILL; ws.cell(2, 2).border = BORDER
        for di in range(DAYS):
            for h in range(export_hours):
                col = 3 + di * export_hours + h
                cell = ws.cell(2, col, _hour_label(h))
                cell.font = WHITE_BOLD; cell.fill = DAY_FILL; cell.alignment = CENTER
                cell.border = Border(left=thick, right=thin, top=thin, bottom=thin) if h == 0 else BORDER
        for ri, name in enumerate(row_names):
            er = 3 + ri
            tc = ws.cell(er, 1, name); tc.font = DARK_BOLD; tc.fill = TEACHER_FILL
            tc.alignment = LEFT; tc.border = BORDER
            tc2 = ws.cell(er, 2, totals[name]); tc2.font = DARK_BOLD
            tc2.fill = TEACHER_FILL; tc2.alignment = CENTER; tc2.border = BORDER
            for di in range(DAYS):
                for h in range(export_hours):
                    col = 3 + di * export_hours + h
                    val = cell_lookup(name, di, h)
                    cell = ws.cell(er, col, val); cell.alignment = CENTER
                    cell.border = Border(left=thick, right=thin, top=thin, bottom=thin) if h == 0 else BORDER
                    if val: cell.font = CLASS_FONT; cell.fill = CLASS_FILL
                    else: cell.fill = EMPTY_FILL
        ws.column_dimensions["A"].width = 26; ws.column_dimensions["B"].width = 7
        for col in range(3, 3 + DAYS * export_hours):
            ws.column_dimensions[get_column_letter(col)].width = 6
        ws.row_dimensions[1].height = 18; ws.row_dimensions[2].height = 16
        for ri in range(len(row_names)): ws.row_dimensions[3 + ri].height = 18
        ws.freeze_panes = "C3"

    # ── helper to draw one individual Day×Hour sheet (one teacher or class) ──
    # No thick separators here — only the overview sheet gets those.
    # Always draws `export_hours` rows (the same global value for every sheet),
    # regardless of whether this particular teacher/class uses all of them.
    def _draw_individual_sheet(ws2, cell_lookup):
        ws2.merge_cells("A1:A2")
        ws2.cell(1, 1, "Ora").font = WHITE_BOLD; ws2.cell(1, 1).fill = HEADER_FILL
        ws2.cell(1, 1).alignment = CENTER; ws2.cell(1, 1).border = BORDER
        for di, dn in enumerate(DAY_NAMES_RO):
            col = 2 + di
            cell = ws2.cell(1, col, dn); cell.font = WHITE_BOLD; cell.fill = DAY_FILL
            cell.alignment = CENTER; cell.border = BORDER
            ws2.column_dimensions[get_column_letter(col)].width = 25
        for h in range(export_hours):
            row_idx = 3 + h
            hc = ws2.cell(row_idx, 1, _hour_label(h)); hc.font = DARK_BOLD
            hc.fill = TEACHER_FILL; hc.border = BORDER; hc.alignment = CENTER
            for di in range(DAYS):
                col_idx = 2 + di
                text = cell_lookup(di, h)
                cell = ws2.cell(row_idx, col_idx, text)
                cell.alignment = CENTER; cell.border = BORDER
                if text: cell.font = CLASS_FONT; cell.fill = CLASS_FILL
                else: cell.fill = EMPTY_FILL
        ws2.column_dimensions["A"].width = 12
        for r in range(1, export_hours + 3): ws2.row_dimensions[r].height = 35

    # ═══════════════════ TEACHERS WORKBOOK ═══════════════════
    wb = Workbook()
    ws_overview = wb.active
    ws_overview.title = "Orar profesori"
    teacher_names = sorted(teacher_grid)
    _draw_overview_sheet(
        ws_overview,
        teacher_names,
        cell_lookup=lambda name, di, h: teacher_grid[name].get((di, h), ""),
        totals={t: len(teacher_grid[t]) for t in teacher_names},
    )

    # one sheet per individual teacher — always export_hours rows
    for tname in teacher_names:
        safe_name = "".join(c for c in tname if c not in '\\/*?:[]')[:31] or "Profesor"
        base_name, suffix = safe_name, 1
        while base_name in wb.sheetnames:
            suffix += 1
            base_name = f"{safe_name[:28]}_{suffix}"
        ws_t = wb.create_sheet(title=base_name)

        teacher_slots: dict[tuple[int, int], tuple[str, str]] = {}
        for class_name, sc in school_classes_map.items():
            for (day, hour), slot in sc.schedule.slots.items():
                if slot is not None and slot.teacher.name == tname:
                    teacher_slots[(day, hour)] = (class_name, slot.subject.name)

        def _teacher_cell_text(di, h, _slots=teacher_slots):
            info = _slots.get((di, h))
            return f"{info[0]}\n({info[1]})" if info else ""

        _draw_individual_sheet(ws_t, _teacher_cell_text)

    t_buf = io.BytesIO(); wb.save(t_buf); teacher_bytes = t_buf.getvalue()

    # ═══════════════════ CLASSES WORKBOOK ═══════════════════
    wb2 = Workbook(); wb2.remove(wb2.active)
    for class_name, sc in sorted(school_classes_map.items()):
        ws2 = wb2.create_sheet(title=class_name)

        def _class_cell_text(di, h, sc=sc):
            info = sc.schedule.get_slot_display(di, h)
            if not info:
                return ""
            parts = info.split(" - ")
            return f"{parts[0]}\n({parts[2]})" if len(parts) >= 3 else parts[0]

        _draw_individual_sheet(ws2, _class_cell_text)

    c_buf = io.BytesIO(); wb2.save(c_buf); class_bytes = c_buf.getvalue()
    return teacher_bytes, class_bytes


def _build_template_bytes() -> bytes:
    wb = Workbook()
    ws1 = wb.active; ws1.title = "school_schedule"
    ws1.append(["ClassName", "Subject", "Teacher", "NumberOfClasses"])
    ws2 = wb.create_sheet("teachers"); ws2.append(["Teacher", "Mon", "Tue", "Wed", "Thu", "Fri"])
    ws3 = wb.create_sheet("classes");  ws3.append(["ClassName", "MinClasses", "MaxClasses"])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# API Routes  — ALL must be defined BEFORE the SPA catch-all below
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/debug/{session_id}")
async def debug_session(session_id: str):
    sess = _session.get(session_id)
    if not sess:
        return {"error": "session not found", "all_sessions": list(_session.keys())}
    return {
        "keys": list(sess.keys()),
        "has_grids": "grids" in sess,
        "has_school_classes_map": "school_classes_map" in sess,
    }


@app.get("/api/template")
async def download_template():
    data = _build_template_bytes()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=schedule_template.xlsx"},
    )


@app.post("/api/upload", response_model=ParsedData)
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx / .xls files are accepted.")
    data = await file.read()
    try:
        return _parse_excel(data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {e}")


@app.post("/api/session/restore", response_model=RestoreSessionResponse)
async def restore_session(req: RestoreSessionRequest):
    """Recreates a working session from a previously saved project file.

    Rebuilds the solver context from `classes`/`teachers` exactly like
    /api/solve/stream does, then replays the saved slot placement from
    `grids` directly onto that context — no solving required, so the
    restored schedule is pixel-for-pixel what was saved, even if it would
    no longer satisfy the original constraints (e.g. they were hand-edited
    via swaps before saving).
    """
    fake_solve_req = SolveRequest(
        session_id="restore",  # unused by _build_context itself
        classes=req.classes,
        teachers=req.teachers,
    )
    try:
        context, school_classes_map, teachers_map = _build_context(fake_solve_req)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not rebuild session from saved data: {e}")

    # index each class's subject requirements by subject name so we can
    # recover the (subject, room) objects referenced by the saved slots
    req_by_class_subject: dict[tuple[str, str], Any] = {}
    for class_name, sc in school_classes_map.items():
        for r in sc.subject_requirements:
            req_by_class_subject[(class_name, r.subject.name)] = r

    grids = req.grids
    for class_name, grid in grids.class_schedules.items():
        sc = school_classes_map.get(class_name)
        if sc is None:
            continue
        for day in range(min(DAYS, len(grid))):
            for hour in range(min(HOURS, len(grid[day]))):
                slot = grid[day][hour]
                if slot is None:
                    continue
                teacher = teachers_map.get(slot.teacher)
                req_obj = req_by_class_subject.get((class_name, slot.subject))
                if teacher is None or req_obj is None:
                    # Saved slot references a teacher/subject that no longer
                    # exists in the (possibly edited) classes/teachers payload —
                    # skip it rather than failing the whole restore.
                    continue
                scheduled = ScheduledClass(
                    school_class=sc, subject=req_obj.subject,
                    teacher=teacher, room=req_obj.room, day=day, hour=hour,
                )
                sc.schedule.assign(day, hour, scheduled)
                teacher.schedule.assign(day, hour, scheduled)

    session_id = str(uuid.uuid4())
    rebuilt_grids = _extract_grids(school_classes_map, teachers_map)
    _session[session_id] = {
        "school_classes_map": school_classes_map,
        "teachers_map":       teachers_map,
        "grids":              rebuilt_grids,
    }

    return RestoreSessionResponse(
        session_id=session_id,
        classes=req.classes,
        teachers=req.teachers,
        grids=rebuilt_grids,
    )


@app.post("/api/solve/stream")
async def solve_stream(req: SolveRequest):
    if req.session_id not in _session:
        raise HTTPException(status_code=404, detail="Session not found. Upload a file first.")

    async def event_generator():
        log_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _emit(obj: dict):
            loop.call_soon_threadsafe(log_queue.put_nowait, obj)

        cancel_event = threading.Event()
        _session[req.session_id]["cancel_event"] = cancel_event

        def _run_solver():
            try:
                existing = _session[req.session_id].get("school_classes_map")
                if existing:
                    school_classes_map = existing
                    teachers_map = _session[req.session_id]["teachers_map"]
                    context = SchedulerContext(
                        classes=list(school_classes_map.values()),
                        teachers=list(teachers_map.values()),
                        rooms=[r for sc in school_classes_map.values() for r in {req.room.name: req.room for req in sc.subject_requirements}.values()],
                    )
                else:
                    context, school_classes_map, teachers_map = _build_context(req)

                import builtins
                orig_print = builtins.print
                _last_forward = [0.0]

                def _patched_print(*args, **kwargs):
                    msg = " ".join(str(a) for a in args)
                    orig_print(msg)
                    is_key = (
                        "solution" in msg.lower()
                        or msg.startswith("[DEBUG]")
                        or "INFEASIBLE" in msg
                        or "FAILED" in msg
                        or "passed" in msg.lower()
                    )
                    now = time.monotonic()
                    if is_key or (now - _last_forward[0] >= 2.0):
                        _last_forward[0] = now
                        loop.call_soon_threadsafe(
                            log_queue.put_nowait,
                            {"type": "log", "message": msg},
                        )

                builtins.print = _patched_print
                try:
                    _emit({"type": "log", "message": (
                        f"Solver started — {len(req.classes)} classes, "
                        f"{len(req.teachers)} teachers, "
                        f"max {req.max_solutions} solution(s)"
                    )})
                    scheduler = Scheduler(context)
                    success = scheduler.solve_cpsat(time_limit=120.0, cancel_event=cancel_event)
                    scheduler.diagnose_infeasibility(time_limit=60.0)
                    # success = scheduler.solve_top_n(
                    #     max_solutions=req.max_solutions,
                    #     cancel_event=cancel_event,
                    # )
                finally:
                    builtins.print = orig_print

                if success:
                    grids = _extract_grids(school_classes_map, teachers_map)
                    _session[req.session_id]["grids"]              = grids
                    _session[req.session_id]["school_classes_map"] = school_classes_map
                    _session[req.session_id]["teachers_map"]       = teachers_map
                    _emit({"type": "log", "message": "✓ Solution found!"})
                    _emit({"type": "done", "success": True, "solutions": getattr(scheduler, "_solutions_found", 1)})
                else:
                    _emit({"type": "log", "message": "✗ No solution found."})
                    _emit({"type": "done", "success": False, "solutions": 0})

            except Exception:
                import traceback
                _emit({"type": "error", "message": traceback.format_exc()})

        thread = threading.Thread(target=_run_solver, daemon=True)
        thread.start()

        finished = False
        while not finished:
            try:
                obj = await asyncio.wait_for(log_queue.get(), timeout=0.2)

                # intercept solution-count log lines to emit a progress event
                if obj.get("type") == "log":
                    msg = obj.get("message", "")
                    if "solution #" in msg.lower():
                        try:
                            # message format: "[DEBUG] solution #N score=..."
                            n = int(msg.lower().split("solution #")[1].split()[0])
                            loop.call_soon_threadsafe(
                                log_queue.put_nowait,
                                {"type": "progress", "solutions": n},
                            )
                        except (IndexError, ValueError):
                            pass

                yield f"data: {json.dumps(obj)}\n\n"

                if obj.get("type") in ("done", "error"):
                    finished = True

            except asyncio.TimeoutError:
                if not thread.is_alive() and log_queue.empty():
                    # thread died without emitting done — guard against stuck UI
                    yield f"data: {json.dumps({'type': 'done', 'success': False, 'solutions': 0})}\n\n"
                    finished = True
                else:
                    yield ": heartbeat\n\n"
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.post("/api/solve/cancel")
async def cancel_solve(session_id: str):
    sess = _session.get(session_id)
    if not sess or "cancel_event" not in sess:
        raise HTTPException(status_code=404, detail="No running solve for this session.")
    sess["cancel_event"].set()
    return {"cancelled": True}

@app.get("/api/schedule/{session_id}", response_model=ScheduleGrid)
async def get_schedule(session_id: str):
    sess = _session.get(session_id)
    if not sess or "grids" not in sess:
        raise HTTPException(status_code=404, detail="No solved schedule for this session.")
    return sess["grids"]


@app.post("/api/swap/candidates", response_model=list[SwapCandidate])
async def get_swap_candidates(req: SwapCandidatesRequest):
    sess = _session.get(req.session_id)
    if not sess or "school_classes_map" not in sess:
        raise HTTPException(status_code=404, detail="Session or schedule not found.")

    school_classes_map: dict[str, SchoolClass] = sess["school_classes_map"]
    teachers_map:       dict[str, Teacher]     = sess["teachers_map"]

    sc_a = school_classes_map.get(req.class_name)
    if sc_a is None:
        raise HTTPException(status_code=404, detail=f"Class {req.class_name} not found.")

    slot_a = sc_a.schedule.get(req.day, req.hour)
    if slot_a is None:
        raise HTTPException(status_code=400, detail="Source slot is empty.")

    teacher_a = slot_a.teacher
    candidates: list[SwapCandidate] = []

    for cname, sc_b in school_classes_map.items():
        for day_b in range(DAYS):
            for hour_b in range(HOURS):
                if cname == req.class_name and day_b == req.day and hour_b == req.hour:
                    continue

                slot_b = sc_b.schedule.get(day_b, hour_b)
                violations: list[str] = []
                can_swap = True

                # Check teacher_a availability at the target slot
                for c in teacher_a.constraints:
                    if isinstance(c, UnavailableTimePeriodConstraint):
                        if (day_b, hour_b) in c._unavailable_set:
                            can_swap = False
                            violations.append(f"{teacher_a.name} unavailable {DAY_NAMES[day_b]}")

                if slot_b is not None:
                    teacher_b = slot_b.teacher

                    if teacher_a.name != teacher_b.name:
                       # teacher_a needs to be free at the target slot (day_b, hour_b)
                        ta_at_target = teacher_a.schedule.get(day_b, hour_b)
                        if ta_at_target is not None:
                            can_swap = False
                            violations.append(f"{teacher_a.name} busy at {DAY_NAMES[day_b]} H{hour_b+1}")
                        # teacher_b needs to be free at the source slot (day_a, hour_a)
                        tb_at_source = teacher_b.schedule.get(req.day, req.hour)
                        if tb_at_source is not None:
                            can_swap = False
                            violations.append(f"{teacher_b.name} busy at {DAY_NAMES[req.day]} H{req.hour+1}")

                    for c in teacher_b.constraints:
                        if isinstance(c, UnavailableTimePeriodConstraint):
                            if (req.day, req.hour) in c._unavailable_set:
                                can_swap = False
                                violations.append(f"{teacher_b.name} unavailable {DAY_NAMES[req.day]}")
                else:
                    # Empty target slot — check teacher_a isn't already teaching elsewhere at that time
                    existing = teacher_a.schedule.get(day_b, hour_b)
                    if existing is not None:
                        can_swap = False
                        violations.append(f"{teacher_a.name} busy at {DAY_NAMES[day_b]} H{hour_b+1}")

                # Mirror the /api/swap late-start rejection here too, so a tile
                # is never shown as a valid ("green") candidate when the actual
                # swap endpoint would reject it for this reason. Skipped for low
                # grades (0-4) — same exemption as /api/swap.
                if can_swap:
                    same_day_reshuffle = (
                        cname == req.class_name and day_b == req.day and slot_b is not None
                    )
                    if not same_day_reshuffle:
                        late_start_msg = _late_start_violation(sc_a, req.day, req.hour, day_b, hour_b, cname)
                        if late_start_msg:
                            can_swap = False
                            violations.append(late_start_msg)
                        if cname != req.class_name:
                            late_start_msg_b = _late_start_violation(sc_b, day_b, hour_b, req.day, req.hour, req.class_name)
                            if late_start_msg_b:
                                can_swap = False
                                violations.append(late_start_msg_b)

                candidates.append(SwapCandidate(
                    class_name=cname, day=day_b, hour=hour_b,
                    status="valid" if can_swap else "invalid",
                    violated_constraints=violations,
                ))

    return candidates

def _day_start_hour(sc: SchoolClass, teacher_for_slot, day: int, exclude=None, add=None) -> int:
    """First occupied hour for `sc` on `day`, after hypothetically removing
    `exclude` (day,hour) and adding `add` (day,hour) as occupied. Returns
    HOURS (i.e. 'none') if the day would end up empty."""
    occupied = set()
    for (d, h), slot in sc.schedule.slots.items():
        if slot is not None and d == day:
            occupied.add(h)
    if exclude and exclude[0] == day:
        occupied.discard(exclude[1])
    if add and add[0] == day:
        occupied.add(add[1])
    return min(occupied) if occupied else HOURS


def _late_start_violation(sc: SchoolClass, day_removed: int, hour_removed: int,
                           day_added: int, hour_added: int, label: str) -> Optional[str]:
    """Returns a human-readable violation message if moving `sc`'s lesson out
    of (day_removed, hour_removed) would push that day's first lesson later —
    or None if the move is fine. Skipped for low grades (0-4): their schedules
    are opportunistic slots filled in as teacher availability allows, not a
    finalized fixed-start schedule, so a shifting "first lesson" isn't a real
    regression yet. Shared by /api/swap (hard rejection) and
    /api/swap/candidates (so candidates are never shown as valid/green when
    the swap endpoint would actually reject them for this reason).
    """
    if sc.grade <= LOW_GRADE_MAX:
        return None
    before = _day_start_hour(sc, None, day_removed, exclude=None, add=None)
    if day_removed == day_added:
        after = _day_start_hour(sc, None, day_removed,
                                 exclude=(day_removed, hour_removed),
                                 add=(day_added, hour_added))
    else:
        # removal and addition are on different days for this class —
        # only the "removed" day can start later as a result of this swap
        after = _day_start_hour(sc, None, day_removed,
                                 exclude=(day_removed, hour_removed),
                                 add=None)
    if before != HOURS and after != HOURS and after > before:
        return (f"{label} would now start later on {DAY_NAMES[day_removed]} "
                f"(H{after + 1} instead of H{before + 1})")
    return None

@app.post("/api/swap")
async def swap_slots(req: SwapRequest):
    sess = _session.get(req.session_id)
    if not sess or "school_classes_map" not in sess:
        raise HTTPException(status_code=404, detail="Session or schedule not found.")

    school_classes_map: dict[str, SchoolClass] = sess["school_classes_map"]
    teachers_map:       dict[str, Teacher]     = sess["teachers_map"]

    sc_a = school_classes_map.get(req.class_name_a)
    sc_b = school_classes_map.get(req.class_name_b)
    if sc_a is None or sc_b is None:
        raise HTTPException(status_code=404, detail="One or both classes not found.")

    slot_a = sc_a.schedule.get(req.day_a, req.hour_a)
    if slot_a is None:
        raise HTTPException(status_code=400, detail="Source slot is empty.")

    slot_b = sc_b.schedule.get(req.day_b, req.hour_b)
    teacher_a = slot_a.teacher
    teacher_b = slot_b.teacher if slot_b is not None else None

    same_cell = (req.class_name_a == req.class_name_b
                 and req.day_a == req.day_b and req.hour_a == req.hour_b)
    if same_cell:
        raise HTTPException(status_code=400, detail="Source and target slot are identical.")

    same_class = req.class_name_a == req.class_name_b

    # ── validate destination slots won't silently clobber unrelated lessons ──
    if not same_class:
        # sc_a is about to receive content at (day_b, hour_b); that cell must
        # currently be empty, UNLESS it's exactly slot_b's cell (already handled).
        existing_at_a_target = sc_a.schedule.get(req.day_b, req.hour_b)
        if existing_at_a_target is not None:
            raise HTTPException(
                status_code=409,
                detail=f"{req.class_name_a} already has a lesson at "
                       f"{DAY_NAMES[req.day_b]} H{req.hour_b + 1}; refusing to overwrite it.",
            )
        existing_at_b_target = sc_b.schedule.get(req.day_a, req.hour_a)
        if existing_at_b_target is not None:
            raise HTTPException(
                status_code=409,
                detail=f"{req.class_name_b} already has a lesson at "
                       f"{DAY_NAMES[req.day_a]} H{req.hour_a + 1}; refusing to overwrite it.",
            )

    # ── validate teacher availability at destination times ──────────────────
    def _unavailable(teacher: Teacher, day: int, hour: int) -> bool:
        for c in teacher.constraints:
            if isinstance(c, UnavailableTimePeriodConstraint):
                if (day, hour) in c._unavailable_set:
                    return True
        return False

    if _unavailable(teacher_a, req.day_b, req.hour_b):
        raise HTTPException(
            status_code=409,
            detail=f"{teacher_a.name} is unavailable at {DAY_NAMES[req.day_b]} H{req.hour_b + 1}.",
        )

    if teacher_b is not None and _unavailable(teacher_b, req.day_a, req.hour_a):
        raise HTTPException(
            status_code=409,
            detail=f"{teacher_b.name} is unavailable at {DAY_NAMES[req.day_a]} H{req.hour_a + 1}.",
        )

    # teacher_a must be free at (day_b, hour_b) unless that's simply where
    # teacher_b's own lesson currently sits (which is moving out of the way)
    ta_at_target = teacher_a.schedule.get(req.day_b, req.hour_b)
    if ta_at_target is not None and ta_at_target is not slot_b:
        raise HTTPException(
            status_code=409,
            detail=f"{teacher_a.name} is already teaching at "
                   f"{DAY_NAMES[req.day_b]} H{req.hour_b + 1}.",
        )

    if teacher_b is not None:
        tb_at_source = teacher_b.schedule.get(req.day_a, req.hour_a)
        if tb_at_source is not None and tb_at_source is not slot_a:
            raise HTTPException(
                status_code=409,
                detail=f"{teacher_b.name} is already teaching at "
                       f"{DAY_NAMES[req.day_a]} H{req.hour_a + 1}.",
            )

    # ── validate the swap doesn't delay either class's start of day ─────────
    # Same class + same day + target already occupied = a same-day reshuffle:
    # both hours stay occupied, only their contents trade places, so the set
    # of occupied hours for that day is unchanged — nothing to check.
    same_day_reshuffle = (
        same_class and req.day_a == req.day_b and slot_b is not None
    )
    if not same_day_reshuffle:
        msg = _late_start_violation(sc_a, req.day_a, req.hour_a, req.day_b, req.hour_b, req.class_name_a)
        if msg:
            raise HTTPException(status_code=409, detail=f"{msg}; swap rejected.")
        if not same_class:
            msg_b = _late_start_violation(sc_b, req.day_b, req.hour_b, req.day_a, req.hour_a, req.class_name_b)
            if msg_b:
                raise HTTPException(status_code=409, detail=f"{msg_b}; swap rejected.")

    # ── all clear — perform the swap ─────────────────────────────────────────
    sc_a.schedule.clear(req.day_a, req.hour_a)
    teacher_a.schedule.clear(req.day_a, req.hour_a)

    if slot_b is not None:
        sc_b.schedule.clear(req.day_b, req.hour_b)
        teacher_b.schedule.clear(req.day_b, req.hour_b)

        new_b = ScheduledClass(
            school_class=slot_b.school_class, subject=slot_b.subject,
            teacher=slot_b.teacher, room=slot_b.room, day=req.day_a, hour=req.hour_a,
        )
        sc_b.schedule.assign(req.day_a, req.hour_a, new_b)
        teacher_b.schedule.assign(req.day_a, req.hour_a, new_b)

    new_a = ScheduledClass(
        school_class=slot_a.school_class, subject=slot_a.subject,
        teacher=slot_a.teacher, room=slot_a.room, day=req.day_b, hour=req.hour_b,
    )
    sc_a.schedule.assign(req.day_b, req.hour_b, new_a)
    teacher_a.schedule.assign(req.day_b, req.hour_b, new_a)

    grids = _extract_grids(school_classes_map, teachers_map)
    sess["grids"] = grids
    return grids

@app.get("/api/export/teacher/{session_id}")
async def export_teacher_schedule(session_id: str):
    sess = _session.get(session_id)
    if not sess or "school_classes_map" not in sess:
        raise HTTPException(status_code=404, detail="No solved schedule.")
    t_bytes, _ = _build_excel_bytes(sess["school_classes_map"], sess["teachers_map"])
    return StreamingResponse(
        io.BytesIO(t_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=teacher_schedule.xlsx"},
    )


@app.get("/api/export/classes/{session_id}")
async def export_class_schedules(session_id: str):
    sess = _session.get(session_id)
    if not sess or "school_classes_map" not in sess:
        raise HTTPException(status_code=404, detail="No solved schedule.")
    _, c_bytes = _build_excel_bytes(sess["school_classes_map"], sess["teachers_map"])
    return StreamingResponse(
        io.BytesIO(c_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=class_schedules.xlsx"},
    )


@app.post("/api/manual/init", response_model=ScheduleGrid)
async def init_manual(req: InitManualRequest):
    """Builds an empty solver context (no solving) so the teacher/class grids
    exist and can be filled in one tile at a time."""
    fake_req = SolveRequest(session_id=req.session_id, classes=req.classes, teachers=req.teachers)
    context, school_classes_map, teachers_map = _build_context(fake_req)
    grids = _extract_grids(school_classes_map, teachers_map)  # all-empty grids
    _session[req.session_id]["school_classes_map"] = school_classes_map
    _session[req.session_id]["teachers_map"] = teachers_map
    _session[req.session_id]["grids"] = grids
    return grids


class ManualCandidate(BaseModel):
    class_name: str
    subject: str
    valid: bool
    reason: Optional[str] = None


@app.get("/api/manual/candidates", response_model=list[ManualCandidate])
async def manual_candidates(session_id: str, teacher: str, day: int, hour: int):
    sess = _session.get(session_id)
    if not sess or "school_classes_map" not in sess:
        raise HTTPException(status_code=404, detail="Session not found.")
    school_classes_map = sess["school_classes_map"]
    teachers_map = sess["teachers_map"]
    t = teachers_map.get(teacher)
    if t is None:
        raise HTTPException(status_code=404, detail="Teacher not found.")

    if not t.schedule.is_free(day, hour):
        raise HTTPException(status_code=400, detail="Teacher already busy at this slot.")
    for c in t.constraints:
        if isinstance(c, UnavailableTimePeriodConstraint) and (day, hour) in c._unavailable_set:
            raise HTTPException(status_code=400, detail="Teacher unavailable at this slot.")

    out = []
    for cname, sc in school_classes_map.items():
        for req in sc.subject_requirements:
            if req.teacher.name != teacher:
                continue
            already = sum(
                1 for slot in sc.schedule.slots.values()
                if slot and slot.subject.name == req.subject.name and slot.teacher.name == teacher
            )
            if already >= req.sessions_per_week:
                continue
            if not sc.schedule.is_free(day, hour):
                out.append(ManualCandidate(class_name=cname, subject=req.subject.name, valid=False, reason="Class already has a lesson then."))
                continue
            out.append(ManualCandidate(class_name=cname, subject=req.subject.name, valid=True))
    return out


@app.post("/api/manual/place", response_model=ScheduleGrid)
async def manual_place(req: ManualPlaceRequest):
    sess = _session.get(req.session_id)
    if not sess or "school_classes_map" not in sess:
        raise HTTPException(status_code=404, detail="Session not found.")
    school_classes_map = sess["school_classes_map"]
    teachers_map = sess["teachers_map"]
    sc = school_classes_map.get(req.class_name)
    teacher = teachers_map.get(req.teacher)
    if sc is None or teacher is None:
        raise HTTPException(status_code=404, detail="Class or teacher not found.")
    req_obj = next((r for r in sc.subject_requirements if r.subject.name == req.subject and r.teacher.name == req.teacher), None)
    if req_obj is None:
        raise HTTPException(status_code=400, detail=f"{req.teacher} doesn't teach {req.subject} to {req.class_name}.")
    if not sc.schedule.is_free(req.day, req.hour) or not teacher.schedule.is_free(req.day, req.hour):
        raise HTTPException(status_code=409, detail="Slot is no longer free.")

    scheduled = ScheduledClass(school_class=sc, subject=req_obj.subject, teacher=teacher, room=req_obj.room, day=req.day, hour=req.hour)
    sc.schedule.assign(req.day, req.hour, scheduled)
    teacher.schedule.assign(req.day, req.hour, scheduled)

    grids = _extract_grids(school_classes_map, teachers_map)
    sess["grids"] = grids
    return grids


@app.post("/api/manual/clear", response_model=ScheduleGrid)
async def manual_clear(req: ManualClearRequest):
    sess = _session.get(req.session_id)
    if not sess or "school_classes_map" not in sess:
        raise HTTPException(status_code=404, detail="Session not found.")
    teachers_map = sess["teachers_map"]
    teacher = teachers_map.get(req.teacher)
    if teacher is None:
        raise HTTPException(status_code=404, detail="Teacher not found.")
    slot = teacher.schedule.get(req.day, req.hour)
    if slot is None:
        raise HTTPException(status_code=400, detail="Slot is already empty.")
    slot.school_class.schedule.clear(req.day, req.hour)
    teacher.schedule.clear(req.day, req.hour)
    grids = _extract_grids(sess["school_classes_map"], teachers_map)
    sess["grids"] = grids
    return grids

# ─────────────────────────────────────────────────────────────────────────────
# SPA catch-all — MUST be last
# ─────────────────────────────────────────────────────────────────────────────

_frontend = Path(__file__).parent / "frontend" / "dist"
if _frontend.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend / "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    async def serve_spa_root():
        index = _frontend / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404, detail="Frontend not built")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str = ""):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not found")
        index = _frontend / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404, detail="Frontend not built")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")