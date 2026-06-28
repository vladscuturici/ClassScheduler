from pydantic import BaseModel, Field
from models.schedule import Schedule
from models.subject import Subject
from models.constraints.constraint import Constraint

class Room(BaseModel):
    name: str
    specific_subject: Subject | None = None
    schedule: Schedule = Field(default_factory=Schedule.empty)
    constraints: list[Constraint] = Field(default_factory=list)