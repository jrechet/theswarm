"""Entities for the Dev-rigour bounded context (Phase E)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.dev_rigour.value_objects import (
    FindingSeverity,
    PreflightDecision,
    TddPhase,
    ThoughtKind,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rand(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


@dataclass(frozen=True)
class DevThought:
    """A single entry in the Dev exploration/research thoughts stream."""

    id: str
    project_id: str
    codename: str = ""
    kind: ThoughtKind = ThoughtKind.NOTE
    task_id: str = ""  # optional link to a ticket/task
    content: str = ""
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("thought")


@dataclass(frozen=True)
class TddArtifact:
    """A RED→GREEN (optionally REFACTOR) TDD-gate artifact for a task."""

    id: str
    project_id: str
    task_id: str
    codename: str = ""
    phase: TddPhase = TddPhase.RED
    test_files: tuple[str, ...] = ()
    red_commit: str = ""  # sha of commit that recorded the failing test
    green_commit: str = ""  # sha of commit where tests pass
    notes: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("tdd")

    @property
    def is_green(self) -> bool:
        return self.phase in (TddPhase.GREEN, TddPhase.REFACTOR)


@dataclass(frozen=True)
class RefactorPreflight:
    """Record of a pre-refactor check when a diff deletes ≥ threshold lines."""

    id: str
    project_id: str
    pr_url: str = ""
    task_id: str = ""
    codename: str = ""
    deletion_lines: int = 0
    files_touched: tuple[str, ...] = ()
    callers_checked: tuple[str, ...] = ()
    decision: PreflightDecision = PreflightDecision.PROCEED
    reason: str = ""
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("preflight")


@dataclass(frozen=True)
class SelfReviewFinding:
    """A single issue raised by the Dev self-review prompt."""

    severity: FindingSeverity = FindingSeverity.LOW
    category: str = ""  # e.g. "naming", "duplication", "missing-tests"
    message: str = ""
    waived: bool = False
    waive_reason: str = ""


@dataclass(frozen=True)
class SelfReview:
    """A Dev self-review pass before opening a PR."""

    id: str
    project_id: str
    pr_url: str = ""
    task_id: str = ""
    codename: str = ""
    findings: tuple[SelfReviewFinding, ...] = ()
    summary: str = ""
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("selfrev")

    @property
    def high_count(self) -> int:
        return sum(
            1
            for f in self.findings
            if f.severity in (FindingSeverity.HIGH, FindingSeverity.CRITICAL)
            and not f.waived
        )

    @property
    def waived_count(self) -> int:
        return sum(1 for f in self.findings if f.waived)


@dataclass(frozen=True)
class CoverageDelta:
    """Changed-lines coverage delta reported on a PR."""

    id: str
    project_id: str
    pr_url: str = ""
    task_id: str = ""
    codename: str = ""
    total_before_pct: float = 0.0
    total_after_pct: float = 0.0
    changed_lines_pct: float = 0.0
    changed_lines: int = 0
    missed_lines: int = 0
    threshold_pct: float = 80.0
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("covd")

    @property
    def delta(self) -> float:
        return round(self.total_after_pct - self.total_before_pct, 2)

    @property
    def passes_threshold(self) -> bool:
        return self.changed_lines_pct >= self.threshold_pct
