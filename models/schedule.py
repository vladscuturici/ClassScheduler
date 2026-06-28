from __future__ import annotations
from pydantic import BaseModel
from typing import Optional, TYPE_CHECKING
from pydantic import Field

if TYPE_CHECKING:
    from models.scheduled_class import ScheduledClass

class Schedule(BaseModel):
    slots: dict[tuple[int, int], Optional[ScheduledClass]] = Field(default_factory=dict)
    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def empty(cls) -> "Schedule":
        return cls(slots={
            (day, hour): None
            for day in range(5)
            for hour in range(8)
        })

    def assign(self, day: int, hour: int, value: "ScheduledClass"):
        self.slots[(day, hour)] = value

    def clear(self, day: int, hour: int):
        self.slots[(day, hour)] = None

    def is_free(self, day: int, hour: int) -> bool:
        return self.slots.get((day, hour)) is None

    def get(self, day: int, hour: int) -> Optional["ScheduledClass"]:
        return self.slots.get((day, hour))

    def slots_for_day(self, day: int) -> list[Optional["ScheduledClass"]]:
        return [self.slots.get((day, h)) for h in range(8)]

    def assigned_slots(self) -> list[tuple[int, int]]:
        return [(d, h) for (d, h), v in self.slots.items() if v is not None]
    
    def get_class_name(self, day: int, hour: int) -> Optional[str]:
        slot = self.slots.get((day, hour))
        if slot is None:
            return None
        return f"{slot.school_class.grade}{slot.school_class.version}"
    
    def get_subject_name(self, day: int, hour: int) -> Optional[str]:
        slot = self.slots.get((day, hour))
        if slot is None:
            return None
        return slot.subject.name

    def get_slot_display(self, day: int, hour: int) -> Optional[str]:
        slot = self.slots.get((day, hour))
        if slot is None:
            return None
        return f"{slot.subject.name} - {slot.school_class.grade}{slot.school_class.version} - {slot.teacher.name}"
    
    def subject_names_for_day(self, day: int) -> list[Optional[str]]:
        return [
            slot.subject.name if slot is not None else None
            for slot in self.slots_for_day(day)
        ]
    
    def weekly_session_count(self) -> int:
        return sum(1 for v in self.slots.values() if v is not None)
    
    def clear_all(self):
        for day in range(5):
            for hour in range(8):
                self.slots[(day, hour)] = None

    def has_any_on_day(self, day: int) -> bool:
        return any(
            self.slots.get((day, hour)) is not None
            for hour in range(8)
        )
        