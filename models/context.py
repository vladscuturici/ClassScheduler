from pydantic import BaseModel
from models.teacher import Teacher
from models.room import Room
from models.school_class import SchoolClass

class SchedulerContext(BaseModel):
    classes: list[SchoolClass]
    teachers: list[Teacher]
    rooms: list[Room]

    model_config = {"arbitrary_types_allowed": True}