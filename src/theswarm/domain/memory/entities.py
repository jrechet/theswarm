"""Entities for the Memory bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope


@dataclass(frozen=True)
class MemoryEntry:
    """A single learning from an agent."""

    category: MemoryCategory
    content: str
    agent: str
    scope: ProjectScope = field(default_factory=ProjectScope)
    cycle_date: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "content": self.content,
            "agent": self.agent,
            "project_id": self.scope.project_id,
            "cycle_date": self.cycle_date,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryEntry:
        return cls(
            category=MemoryCategory(data.get("category", "errors")),
            content=data.get("content", ""),
            agent=data.get("agent", ""),
            scope=ProjectScope(project_id=data.get("project_id", "")),
            cycle_date=data.get("cycle_date", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
        )

    def promote_to_global(self) -> MemoryEntry:
        """Promote a project-scoped entry to global scope."""
        return MemoryEntry(
            category=MemoryCategory.CROSS_PROJECT,
            content=self.content,
            agent=self.agent,
            scope=ProjectScope(),
            cycle_date=self.cycle_date,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class Retrospective:
    """A cycle retrospective producing learnings."""

    cycle_date: str
    project_id: str
    entries: tuple[MemoryEntry, ...] = ()

    @property
    def count(self) -> int:
        return len(self.entries)
