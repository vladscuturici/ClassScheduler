from pydantic import BaseModel
from models.teacher import Teacher
from models.subject import Subject
from models.room import Room
from models.school_class import SchoolClass

class ScheduledClass(BaseModel):
    school_class: SchoolClass
    subject: Subject
    teacher: Teacher
    room: Room
    day: int
    hour: int

    model_config = {"arbitrary_types_allowed": True}