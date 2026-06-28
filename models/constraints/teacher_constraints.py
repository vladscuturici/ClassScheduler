from __future__ import annotations

from pydantic import model_validator
from models.teacher import Teacher
from models.constraints.constraint import Constraint
from models.context import SchedulerContext


class TeacherConstraint(Constraint):
    teacher: Teacher


class UnavailableTimePeriodConstraint(TeacherConstraint):
    unavailable_slots: list[tuple[int, int]]

    # Private set built at construction time for O(1) lookups in _slot_free.
    # Pydantic ignores fields starting with underscore by default, so we
    # store it as a plain Python attribute via model_validator.
    _unavailable_set: set[tuple[int, int]] = set()

    @model_validator(mode="after")
    def _build_set(self) -> "UnavailableTimePeriodConstraint":
        self._unavailable_set = {(d, h) for d, h in self.unavailable_slots}
        return self

    def check(self, context: "SchedulerContext") -> bool:
        for day, hour in self.unavailable_slots:
            if not self.teacher.schedule.is_free(day, hour):
                return False
        return True

class MaxTeacherGapConstraint(TeacherConstraint):
    max_gap: int = 1
    max_gaps_per_day: int = 1  # new: max number of gap occurrences per day

    def affects(self, school_class=None, teacher=None, room=None) -> bool:
        return teacher is self.teacher

    def check(self, context: "SchedulerContext") -> bool:
        for day in range(5):
            occupied = sorted(
                hour for hour in range(8)
                if not self.teacher.schedule.is_free(day, hour)
            )
            gap_count = 0
            for i in range(len(occupied) - 1):
                gap = occupied[i + 1] - occupied[i] - 1
                if gap > self.max_gap:
                    return False
                if gap > 0:
                    gap_count += 1
            if gap_count > self.max_gaps_per_day:
                return False
        return True