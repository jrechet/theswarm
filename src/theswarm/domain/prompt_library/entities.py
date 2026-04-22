"""Entities for prompt library (Phase L)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.prompt_library.value_objects import PromptAuditAction


@dataclass(frozen=True)
class PromptTemplate:
    """A named prompt template, versioned on every update."""

    id: str
    name: str  # unique key; e.g. "po.morning_plan"
    role: str = ""  # optional role hint
    body: str = ""
    version: int = 1
    deprecated: bool = False
    updated_by: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_active(self) -> bool:
        return not self.deprecated


@dataclass(frozen=True)
class PromptAuditEntry:
    """Append-only audit entry for prompt template changes."""

    id: str
    prompt_name: str
    action: PromptAuditAction
    actor: str = ""
    before_version: int = 0
    after_version: int = 0
    note: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_version_bump(self) -> bool:
        return self.after_version > self.before_version
