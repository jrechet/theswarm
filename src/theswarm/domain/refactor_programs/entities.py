"""Entities for the refactor-programs bounded context (Phase L)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.refactor_programs.value_objects import (
    RefactorProgramStatus,
)


@dataclass(frozen=True)
class RefactorProgram:
    """A coordinated refactor program spanning multiple projects."""

    id: str
    title: str
    rationale: str = ""
    status: RefactorProgramStatus = RefactorProgramStatus.PROPOSED
    target_projects: tuple[str, ...] = field(default_factory=tuple)
    owner: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_active(self) -> bool:
        return self.status == RefactorProgramStatus.ACTIVE

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            RefactorProgramStatus.COMPLETED,
            RefactorProgramStatus.CANCELLED,
        )

    @property
    def project_count(self) -> int:
        return len(self.target_projects)
