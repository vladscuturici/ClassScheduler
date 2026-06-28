from pydantic import BaseModel, Field
from models.schedule import Schedule
from models.subject import Subject
from models.constraints.constraint import Constraint

class Teacher(BaseModel):
    name: str
    subjects: list[Subject]
    schedule: Schedule = Field(default_factory=Schedule.empty)
    constraints: list[Constraint] = Field(default_factory=list)