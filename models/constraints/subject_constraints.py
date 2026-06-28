from __future__ import annotations
from models.constraints.constraint import Constraint
from models.subject import Subject
from models.schedule import Schedule
from models.context import SchedulerContext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.context import SchedulerContext

class SubjectConstraint(Constraint):
    subject: Subject

class MaxConsecutiveClassesConstraint(SubjectConstraint):
    max_classes: int

    def check(self, context: SchedulerContext) -> bool:
        for school_class in context.classes:
            schedule = school_class.schedule
            for day in range(5):
                runs = []
                current_run = 0

                for hour in range(0, 8):
                    if schedule.get_subject_name(day, hour) == self.subject.name:
                        current_run += 1
                    else:
                        if current_run > 0:
                            runs.append(current_run)
                            current_run = 0

                if current_run > 0:
                    runs.append(current_run)

                if any(run > self.max_classes for run in runs):
                    return False

                if len(runs) > 1:
                    return False

        return True


class MaxClassesPerDayConstraint(SubjectConstraint):
    max_classes: int

    def check(self, context: SchedulerContext) -> bool:
        for school_class in context.classes:
            schedule = school_class.schedule
            for day in range(5):
                daily_classes = sum(
                    1 for slot in schedule.slots_for_day(day)
                    if slot is not None and slot.subject.name == self.subject.name
                )
                if daily_classes > self.max_classes:
                    return False
        return True
    
class TimePreferenceConstraint(SubjectConstraint):

    def _hour_points(self, hour: int) -> int:
        raise NotImplementedError

    def score(self, context: SchedulerContext) -> int:
        total_points = 0
        total_sessions = 0

        for school_class in context.classes:
            schedule = school_class.schedule
            for day in range(5):
                for hour in range(8):
                    if schedule.get_subject_name(day, hour) == self.subject.name:
                        total_sessions += 1
                        total_points += self._hour_points(hour)

        if total_sessions == 0:
            return 100

        return int((total_points / (total_sessions * 10)) * 100)


class EarlyClassesPreferenceConstraint(TimePreferenceConstraint):
    def _hour_points(self, hour: int) -> int:
        if hour < 2: return 10
        if hour < 4: return 5
        return 0

class LateClassesPreferenceConstraint(TimePreferenceConstraint):
    def _hour_points(self, hour: int) -> int:
        if hour > 4: return 10
        if hour > 2: return 5
        return 0
    
class LastClassConstraint(SubjectConstraint):
    def _is_last_slot(self, schedule: Schedule, day: int, hour: int) -> bool:
        for h in range(hour + 1, 8):
            if schedule.get(day, h) is not None:
                return False
        return True

    def check(self, context: SchedulerContext) -> bool:
        for school_class in context.classes:
            schedule = school_class.schedule
            for day in range(5):
                for hour in range(8):
                    if schedule.get_subject_name(day, hour) == self.subject.name:
                        if not self._is_last_slot(schedule, day, hour):
                            return False
        return True

class LastClassPreferenceConstraint(SubjectConstraint):
    def _is_last_slot(self, schedule: Schedule, day: int, hour: int) -> bool:
        for h in range(hour + 1, 8):
            if schedule.get(day, h) is not None:
                return False
        return True

    def score(self, context: SchedulerContext) -> int:
        total_points = 0
        total_sessions = 0

        for school_class in context.classes:
            schedule = school_class.schedule
            for day in range(5):
                for hour in range(8):
                    if schedule.get_subject_name(day, hour) == self.subject.name:
                        total_sessions += 1
                        if self._is_last_slot(schedule, day, hour):
                            total_points += 10

        if total_sessions == 0:
            return 100

        return int((total_points / (total_sessions * 10)) * 100)
    
class LastClassStrongPreferenceConstraint(SubjectConstraint):
    """Heavily penalizes any session of this subject that isn't the last of the day."""
    
    def _is_last_slot(self, schedule: Schedule, day: int, hour: int) -> bool:
        for h in range(hour + 1, 8):
            if schedule.get(day, h) is not None:
                return False
        return True

    def score(self, context: SchedulerContext) -> int:
        for school_class in context.classes:
            schedule = school_class.schedule
            for day in range(5):
                for hour in range(8):
                    if schedule.get_subject_name(day, hour) == self.subject.name:
                        if not self._is_last_slot(schedule, day, hour):
                            return -10000  # heavy penalty, not just 0
        return 100