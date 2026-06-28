# test_scheduler.py
from models.subject import Subject
from models.teacher import Teacher
from models.room import Room
from models.school_class import SchoolClass, SubjectRequirement
from models.context import SchedulerContext
from scheduler.scheduler import Scheduler

math = Subject(name="Math", relevance=8)
english = Subject(name="English", relevance=5)

teacher_a = Teacher(name="Alice", subjects=[math])
teacher_b = Teacher(name="Bob", subjects=[english])

room_1 = Room(name="Room 1")

class_10a = SchoolClass(
    grade=10,
    version="A",
    subject_requirements=[
        SubjectRequirement(subject=math, teacher=teacher_a, sessions_per_week=3, room=room_1),
        SubjectRequirement(subject=english, teacher=teacher_b, sessions_per_week=2, room=room_1),
    ]
)

context = SchedulerContext(
    classes=[class_10a],
    teachers=[teacher_a, teacher_b],
    rooms=[room_1]
)

scheduler = Scheduler(context)
success = scheduler.solve()

print("Solved:", success)
if success:
    for day in range(5):
        print(f"\nDay {day}:")
        for hour in range(8):
            slot = class_10a.schedule.get_slot_display(day, hour)
            if slot:
                print(f"  Hour {hour}: {slot}")