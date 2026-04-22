"""Entities for the Writer bounded context (Phase J)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.writer.value_objects import (
    ChangeKind,
    DocKind,
    DocStatus,
    QuickstartOutcome,
)


@dataclass(frozen=True)
class DocArtifact:
    """A piece of documentation tracked by the Writer role."""

    id: str
    project_id: str
    kind: DocKind
    path: str  # repo-relative, e.g. "README.md"
    title: str = ""
    summary: str = ""
    status: DocStatus = DocStatus.DRAFT
    last_reviewed_at: datetime | None = None
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def needs_refresh(self) -> bool:
        return self.status == DocStatus.STALE


@dataclass(frozen=True)
class QuickstartCheck:
    """A verification run of the documented quickstart path."""

    id: str
    project_id: str
    step_count: int = 0
    duration_seconds: float = 0.0
    outcome: QuickstartOutcome = QuickstartOutcome.SKIPPED
    failure_step: str = ""
    note: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_broken(self) -> bool:
        return self.outcome == QuickstartOutcome.FAIL


@dataclass(frozen=True)
class ChangelogEntry:
    """One bullet in the generated changelog, auto-extracted from a PR."""

    id: str
    project_id: str
    kind: ChangeKind
    summary: str
    pr_url: str = ""
    version: str = ""  # populated when bundled into a release
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_breaking(self) -> bool:
        return self.kind == ChangeKind.BREAKING
