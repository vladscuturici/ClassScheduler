from models.schedule import Schedule
from models.subject import Subject
from models.context import SchedulerContext
from models.scheduled_class import ScheduledClass
from scheduler.assignment_class import AssignmentTask
from models.constraints.constraint import Constraint
from models.constraints.subject_constraints import LastClassConstraint, LastClassStrongPreferenceConstraint

import time


class Scheduler:
    def __init__(self, context: SchedulerContext):
        self.context = context
        self._hard_constraints, self._soft_constraints = self._collect_constraints()


    def solve(self) -> bool:
        tasks = self._build_tasks()
        success = self._backtrack(tasks, index=0)
        if not success:
            self._clear_all()
        return success

    def solve_top_n(self, max_solutions: int = 10) -> bool:
        self._max_solutions = max_solutions
        self._solutions_found = 0
        self._best_score = -1
        self._best_slots: dict = {}

        tasks = self._build_tasks()
        self._backtrack_top_n(tasks, index=0)

        if self._best_slots:
            self._restore_best()
            return True
        self._clear_all()
        return False

    def solve_best(self, time_limit: float = 30.0) -> bool:
        self._deadline = time.monotonic() + time_limit
        self._best_score = -1
        self._best_slots: dict = {}

        tasks = self._build_tasks()

        self._max_score_per_constraint = [
            getattr(c, 'max_score', 0) for c in self._soft_constraints
        ]
        self._soft_upper_bound = sum(self._max_score_per_constraint)

        self._backtrack_best(tasks, index=0, current_score=0)

        if self._best_slots:
            self._restore_best()
            return True
        self._clear_all()
        return False

    def _backtrack(self, tasks: list[AssignmentTask], index: int) -> bool:
        if index == len(tasks):
            return True

        task = tasks[index]
        for day, hour, teacher, room in self._get_candidates(task):
            self._assign(task, day, hour, teacher, room)

            if self._check_hard_constraints_incremental(task, day, hour, teacher, room):
                if index + 1 < len(tasks) and not self._get_candidates(tasks[index + 1]):
                    self._unassign(task, day, hour, teacher, room)
                    continue

                if self._backtrack(tasks, index + 1):
                    return True

            self._unassign(task, day, hour, teacher, room)

        return False

    def _backtrack_best(self, tasks: list[AssignmentTask], index: int, current_score: int) -> None:
        if time.monotonic() > self._deadline:
            return

        if index == len(tasks):
            score = self._total_soft_score()
            if score > self._best_score:
                self._best_score = score
                self._best_slots = self._snapshot()
            return
        if current_score + self._soft_upper_bound <= self._best_score:
            return

        task = tasks[index]
        for day, hour, teacher, room in self._get_candidates(task):
            self._assign(task, day, hour, teacher, room)

            if self._check_hard_constraints_incremental(task, day, hour, teacher, room):
                if index + 1 < len(tasks) and not self._get_candidates(tasks[index + 1]):
                    self._unassign(task, day, hour, teacher, room)
                    continue
                self._backtrack_best(tasks, index + 1, current_score=self._total_soft_score())

            self._unassign(task, day, hour, teacher, room)

    def _backtrack_top_n(self, tasks: list[AssignmentTask], index: int) -> bool:
        if self._solutions_found >= self._max_solutions:
            return True

        if index == len(tasks):
            self._solutions_found += 1
            score = self._total_soft_score()
            if score > self._best_score:
                self._best_score = score
                self._best_slots = self._snapshot()
            return False

        task = tasks[index]
        for day, hour, teacher, room in self._get_candidates(task):
            self._assign(task, day, hour, teacher, room)

            if self._check_hard_constraints_incremental(task, day, hour, teacher, room):
                if index + 1 < len(tasks) and not self._get_candidates(tasks[index + 1]):
                    self._unassign(task, day, hour, teacher, room)
                    continue

                should_stop = self._backtrack_top_n(tasks, index + 1)
                if should_stop:
                    self._unassign(task, day, hour, teacher, room)
                    return True

            self._unassign(task, day, hour, teacher, room)

        return False

    def _get_candidates(self, task: AssignmentTask) -> list[tuple]:
        req = task.requirement

        teachers = [req.teacher] if req.teacher else self.context.teachers
        rooms = [req.room] if req.room else [
            r for r in self.context.rooms
            if r.specific_subject is None or r.specific_subject.name == req.subject.name
        ]

        candidates = [
            (day, hour, teacher, room)
            for day in range(5)
            for hour in range(8)
            for teacher in teachers
            for room in rooms
            if self._slot_is_free(task.school_class, teacher, room, day, hour)
        ]
        candidates.sort(key=lambda c: (c[0], c[1]))
        return candidates

    def _slot_is_free(self, school_class, teacher, room, day: int, hour: int) -> bool:
        return (
            school_class.schedule.is_free(day, hour)
            and teacher.schedule.is_free(day, hour)
            and room.schedule.is_free(day, hour)
        )

    def _assign(self, task: AssignmentTask, day: int, hour: int, teacher, room) -> None:
        sc = ScheduledClass(
            school_class=task.school_class,
            subject=task.requirement.subject,
            teacher=teacher,
            room=room,
            day=day,
            hour=hour,
        )
        task.school_class.schedule.assign(day, hour, sc)
        teacher.schedule.assign(day, hour, sc)
        room.schedule.assign(day, hour, sc)

    def _unassign(self, task: AssignmentTask, day: int, hour: int, teacher, room) -> None:
        task.school_class.schedule.clear(day, hour)
        teacher.schedule.clear(day, hour)
        room.schedule.clear(day, hour)

    def _clear_all(self) -> None:
        for cls in self.context.classes:
            cls.schedule.clear_all()
        for teacher in self.context.teachers:
            teacher.schedule.clear_all()
        for room in self.context.rooms:
            room.schedule.clear_all()

    def _collect_constraints(self) -> tuple[list[Constraint], list[Constraint]]:
        seen: set[int] = set()
        hard: list[Constraint] = []
        soft: list[Constraint] = []

        all_constraints: list[Constraint] = []
        for cls in self.context.classes:
            all_constraints.extend(cls.constraints)
            for req in cls.subject_requirements:
                all_constraints.extend(req.subject.constraints)
        for teacher in self.context.teachers:
            all_constraints.extend(teacher.constraints)
        for room in self.context.rooms:
            all_constraints.extend(room.constraints)

        for c in all_constraints:
            cid = id(c)
            if cid in seen:
                continue
            seen.add(cid)

            overrides_check = type(c).check is not Constraint.check
            overrides_score = type(c).score is not Constraint.score

            if overrides_check:
                hard.append(c)
            elif overrides_score:
                soft.append(c)

        return hard, soft

    def _check_hard_constraints_incremental(
        self, task: AssignmentTask, day: int, hour: int, teacher, room
    ) -> bool:
        entities = {
            'school_class': task.school_class,
            'teacher': teacher,
            'room': room,
        }
        for c in self._hard_constraints:
            if hasattr(c, 'affects') and not c.affects(**entities):
                continue
            if not c.check(self.context):
                return False
        return True

    def _total_soft_score(self) -> int:
        return sum(c.score(self.context) for c in self._soft_constraints)

    def _build_tasks(self) -> list[AssignmentTask]:
        tasks: list[AssignmentTask] = []
        for cls in self.context.classes:
            for req in cls.subject_requirements:
                for _ in range(req.sessions_per_week):
                    tasks.append(AssignmentTask(school_class=cls, requirement=req))

        teacher_load: dict[str, int] = {}
        for cls in self.context.classes:
            for req in cls.subject_requirements:
                if req.teacher:
                    name = req.teacher.name
                    teacher_load[name] = teacher_load.get(name, 0) + req.sessions_per_week

        def task_sort_key(t: AssignmentTask) -> tuple:
            has_last = any(
                isinstance(c, (LastClassConstraint, LastClassStrongPreferenceConstraint))
                for c in t.requirement.subject.constraints
            )
            load = teacher_load.get(
                t.requirement.teacher.name if t.requirement.teacher else '', 0
            )
            return (
                1 if has_last else 0,
                -load,
                -len(t.requirement.subject.constraints),
                -max((c.priority for c in t.requirement.subject.constraints), default=0),
                -t.requirement.sessions_per_week,
            )

        tasks.sort(key=task_sort_key)
        return tasks

    def _snapshot(self) -> dict:
        snapshot = {}
        for cls in self.context.classes:
            key = ('class', id(cls))
            snapshot[key] = (
                cls.schedule.snapshot()
                if hasattr(cls.schedule, 'snapshot')
                else dict(cls.schedule.slots)
            )
        for teacher in self.context.teachers:
            key = ('teacher', id(teacher))
            snapshot[key] = (
                teacher.schedule.snapshot()
                if hasattr(teacher.schedule, 'snapshot')
                else dict(teacher.schedule.slots)
            )
        for room in self.context.rooms:
            key = ('room', id(room))
            snapshot[key] = (
                room.schedule.snapshot()
                if hasattr(room.schedule, 'snapshot')
                else dict(room.schedule.slots)
            )
        return snapshot

    def _restore_best(self) -> None:
        for cls in self.context.classes:
            data = self._best_slots[('class', id(cls))]
            if hasattr(cls.schedule, 'restore'):
                cls.schedule.restore(data)
            else:
                cls.schedule.slots = data

        for teacher in self.context.teachers:
            data = self._best_slots[('teacher', id(teacher))]
            if hasattr(teacher.schedule, 'restore'):
                teacher.schedule.restore(data)
            else:
                teacher.schedule.slots = data

        for room in self.context.rooms:
            data = self._best_slots[('room', id(room))]
            if hasattr(room.schedule, 'restore'):
                room.schedule.restore(data)
            else:
                room.schedule.slots = data