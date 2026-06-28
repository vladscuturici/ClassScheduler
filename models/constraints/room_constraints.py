from __future__ import annotations
from models.school_class import SchoolClass
from models.constraints.constraint import Constraint
from models.schedule import Schedule
from models.room import Room
from models.context import SchedulerContext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.context import SchedulerContext

class RoomConstraint(Constraint):
    room: Room

class MaxClassesPerRoomConstraint(RoomConstraint):
    max_classes_per_day: int

    def check(self, context: "SchedulerContext") -> bool:
        for day in range(5):
            daily_count = sum(
                1 for slot in self.room.schedule.slots_for_day(day)
                if slot is not None
            )

            if daily_count > self.max_classes_per_day:
                return False

        return True