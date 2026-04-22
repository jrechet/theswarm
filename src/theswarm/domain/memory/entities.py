"""Entities for the Memory bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope, ScopeLayer


def _infer_scope_layer(project_id: str, role: str) -> ScopeLayer:
    """Derive a scope layer from (project_id, role) when not explicitly supplied."""
    if not project_id:
        return ScopeLayer.GLOBAL
    if role:
        return ScopeLayer.ROLE_PROJECT
    return ScopeLayer.PROJECT


@dataclass(frozen=True)
class MemoryEntry:
    """A single learning from an agent.

    Three-layer memory keying:
      - ``scope.project_id`` empty ⇒ global / cross-project.
      - ``scope.project_id`` set + ``role`` empty ⇒ project-scoped.
      - ``scope.project_id`` set + ``role`` set ⇒ role × project scoped.

    ``codename`` is the human first name bound to this agent instance; ``agent``
    is kept for backwards compatibility and mirrors ``codename`` when both are
    provided, else the role string.
    """

    category: MemoryCategory
    content: str
    agent: str = ""
    scope: ProjectScope = field(default_factory=ProjectScope)
    cycle_date: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    codename: str = ""
    role: str = ""
    scope_layer: ScopeLayer | None = None
    confidence: float = 1.0
    supersedes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_layer",
            self.scope_layer or _infer_scope_layer(self.scope.project_id, self.role),
        )
        # Keep agent field populated for legacy readers.
        if not self.agent:
            object.__setattr__(self, "agent", self.codename or self.role)

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "content": self.content,
            "agent": self.agent,
            "codename": self.codename,
            "role": self.role,
            "scope_layer": (self.scope_layer or ScopeLayer.GLOBAL).value,
            "project_id": self.scope.project_id,
            "cycle_date": self.cycle_date,
            "created_at": self.created_at.isoformat(),
            "confidence": self.confidence,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryEntry:
        scope_layer_raw = data.get("scope_layer")
        return cls(
            category=MemoryCategory.from_str(data.get("category", "errors")),
            content=data.get("content", ""),
            agent=data.get("agent", ""),
            scope=ProjectScope(project_id=data.get("project_id", "")),
            cycle_date=data.get("cycle_date", ""),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            codename=data.get("codename", ""),
            role=data.get("role", ""),
            scope_layer=ScopeLayer(scope_layer_raw) if scope_layer_raw else None,
            confidence=float(data.get("confidence", 1.0)),
            supersedes=data.get("supersedes", ""),
        )

    def promote_to_global(self) -> MemoryEntry:
        """Promote a project-scoped entry to global scope."""
        return MemoryEntry(
            category=MemoryCategory.CROSS_PROJECT,
            content=self.content,
            agent=self.agent,
            codename=self.codename,
            role=self.role,
            scope=ProjectScope(),
            scope_layer=ScopeLayer.GLOBAL,
            cycle_date=self.cycle_date,
            created_at=self.created_at,
            confidence=self.confidence,
            supersedes=self.supersedes,
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
