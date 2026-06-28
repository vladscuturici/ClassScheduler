from pydantic import BaseModel, Field
from models.constraints.constraint import Constraint

class Subject(BaseModel):
    name: str
    relevance: int
    constraints: list[Constraint] = Field(default_factory=list)