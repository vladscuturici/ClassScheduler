from __future__ import annotations
from models.school_class import SchoolClass
from models.constraints.constraint import Constraint
from models.schedule import Schedule
from models.context import SchedulerContext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.context import SchedulerContext


class ClassConstraint(Constraint):
    school_class: SchoolClass


class BalancedDailyDifficultyConstraint(ClassConstraint):
    def score(self, context: "SchedulerContext") -> int:
        daily_sums = []

        for day in range(5):
            daily_total = sum(
                slot.subject.relevance
                for slot in self.school_class.schedule.slots_for_day(day)
                if slot is not None
            )
            daily_sums.append(daily_total)

        if not any(daily_sums):
            return 100

        avg = sum(daily_sums) / 5
        if avg == 0:
            return 100

        avg_deviation = sum(abs(x - avg) for x in daily_sums) / 5
        normalized = avg_deviation / avg

        return max(0, int((1 - normalized) * 100))


class MinDailyClassCount(ClassConstraint):
    min_classes: int

    def check(self, context: "SchedulerContext") -> bool:
        """
        Called by _check_hard() after every slot assignment.

        Strategy: only validate days that are already "closed", i.e. days
        that are fully in the past relative to where the solver currently is.
        A day is considered closed when the class has at least one session
        placed on a *later* day — meaning the solver has moved on and the
        block for that earlier day is final.

        For the current day being filled we cannot enforce the minimum yet
        (more sessions may still be added). We also skip days with zero
        sessions entirely — those are intentional rest days, not violations
        (the MaxDailyClassCount / compactness constraints handle structure).
        """
        schedule = self.school_class.schedule

        # Find the latest day that has any session placed.
        latest_day = -1
        for day in range(4, -1, -1):
            if any(s is not None for s in schedule.slots_for_day(day)):
                latest_day = day
                break

        if latest_day <= 0:
            # Nothing placed yet, or only day 0 touched — nothing to validate.
            return True

        # Validate all days strictly before the latest active day.
        # Those days are "closed": the compact backtracker will never add more
        # sessions to them once it has advanced to a later day.
        for day in range(latest_day):
            daily_count = sum(
                1 for s in schedule.slots_for_day(day) if s is not None
            )
            # A day with zero sessions is a skipped day — allowed.
            # A day with 1..min_classes-1 sessions violates the minimum.
            if 0 < daily_count < self.min_classes:
                return False

        return True


class MaxDailyClassCount(ClassConstraint):
    max_classes: int

    def check(self, context: "SchedulerContext") -> bool:
        for day in range(5):
            daily_classes = sum(
                1 for slot in self.school_class.schedule.slots_for_day(day)
                if slot is not None
            )
            if daily_classes > self.max_classes:
                return False
        return True


class CompactDailyScheduleConstraint(ClassConstraint):
    def check(self, context: "SchedulerContext") -> bool:
        schedule = self.school_class.schedule
        if schedule.weekly_session_count() < self.school_class.total_class_sessions:
            return True

        for day in range(5):
            if schedule.get(day, 0) is None:
                return False

            end = None
            for hour in range(7, -1, -1):
                if schedule.get(day, hour) is not None:
                    end = hour
                    break

            if end is None:
                continue

            for hour in range(0, end + 1):
                if schedule.get(day, hour) is None:
                    return False

        return True
    
class MaxLongDayCountConstraint(ClassConstraint):
    """
    Limits how many days per week a class can hit the 'long day' threshold.
    
    Example: if threshold=7 and max_long_days=2, at most 2 days per week
    can have 7 or more classes scheduled.
    """
    threshold: int      # the daily count that qualifies as a "long day"
    max_long_days: int  # how many such days are allowed per week

    def check(self, context: "SchedulerContext") -> bool:
        long_day_count = 0
        for day in range(5):
            daily_classes = sum(
                1 for slot in self.school_class.schedule.slots_for_day(day)
                if slot is not None
            )
            if daily_classes >= self.threshold:
                long_day_count += 1

        return long_day_count <= self.max_long_days
    