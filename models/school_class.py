from pydantic import BaseModel, Field
from models.schedule import Schedule
from models.subject import Subject
from models.teacher import Teacher
from models.room import Room
from models.constraints.constraint import Constraint

class SubjectRequirement(BaseModel):
    subject: Subject
    teacher: Teacher | None = None
    sessions_per_week: int
    room: Room | None = None

class SchoolClass(BaseModel):
    grade: int
    version: str
    total_class_sessions: int
    subject_requirements: list[SubjectRequirement] = Field(default_factory=list)
    schedule: Schedule = Field(default_factory=Schedule.empty)
    constraints: list[Constraint] = Field(default_factory=list)

    