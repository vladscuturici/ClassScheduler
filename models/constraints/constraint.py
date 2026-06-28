# models/constraints/constraint.py
from __future__ import annotations
from pydantic import BaseModel
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.context import SchedulerContext

class Constraint(BaseModel):
    priority: int

    def check(self, context) -> bool:
        raise NotImplementedError

    def score(self, context) -> int:
        return 100