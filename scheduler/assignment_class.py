from dataclasses import dataclass
from models.school_class import SchoolClass, SubjectRequirement

@dataclass
class AssignmentTask:
    school_class: SchoolClass
    requirement: SubjectRequirement
