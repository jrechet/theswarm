"""Value objects for the Memory bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryCategory(str, Enum):
    STACK = "stack"
    CONVENTIONS = "conventions"
    ERRORS = "errors"
    ARCHITECTURE = "architecture"
    IMPROVEMENTS = "improvements"
    CROSS_PROJECT = "cross_project"


@dataclass(frozen=True)
class ProjectScope:
    """Scope of a memory entry: project-specific or global."""

    project_id: str = ""  # empty = global

    @property
    def is_global(self) -> bool:
        return not self.project_id

    def __str__(self) -> str:
        return self.project_id or "global"
