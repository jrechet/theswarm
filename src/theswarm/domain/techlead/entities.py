"""Entities for the TechLead bounded context."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.techlead.value_objects import (
    ADRStatus,
    DebtSeverity,
    DepSeverity,
    ReviewDecision,
    ReviewOutcome,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rand(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


@dataclass(frozen=True)
class ADR:
    """Architecture Decision Record."""

    id: str
    project_id: str
    number: int  # human-readable ADR number, 1-based per project
    title: str
    status: ADRStatus = ADRStatus.PROPOSED
    context: str = ""
    decision: str = ""
    consequences: str = ""
    supersedes: str | None = None
    tags: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("adr")

    @property
    def slug(self) -> str:
        """Filesystem-friendly slug: `0007-use-event-bus`."""
        cleaned = "".join(
            c if c.isalnum() else "-" for c in self.title.lower()
        ).strip("-")
        cleaned = "-".join(filter(None, cleaned.split("-")))
        return f"{self.number:04d}-{cleaned}"


@dataclass(frozen=True)
class DebtEntry:
    """A known piece of technical debt with severity and blast radius."""

    id: str
    project_id: str
    title: str
    severity: DebtSeverity = DebtSeverity.MEDIUM
    blast_radius: str = ""  # free text: "auth module", "all API clients", ...
    location: str = ""  # file or module path
    owner_codename: str = ""  # which TechLead owns it
    description: str = ""
    resolved: bool = False
    created_at: datetime = field(default_factory=_now)
    resolved_at: datetime | None = None

    @staticmethod
    def new_id() -> str:
        return _rand("debt")

    @property
    def age_days(self) -> int:
        ref = self.resolved_at or _now()
        return max(0, (ref - self.created_at).days)


@dataclass(frozen=True)
class DepFinding:
    """A dependency radar finding (vuln or stale version)."""

    id: str
    project_id: str
    package: str
    installed_version: str = ""
    advisory_id: str = ""  # e.g. CVE-2024-1234, GHSA-xxxx, OSV id
    severity: DepSeverity = DepSeverity.INFO
    summary: str = ""
    fixed_version: str = ""
    source: str = ""  # "pip-audit", "osv-scanner", "gh-advisory", ...
    url: str = ""
    observed_at: datetime = field(default_factory=_now)
    dismissed: bool = False

    @staticmethod
    def new_id() -> str:
        return _rand("dep")


@dataclass(frozen=True)
class CriticalPath:
    """A file/module pattern flagged for second-opinion review."""

    id: str
    project_id: str
    pattern: str  # glob or substring
    reason: str = ""
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("crit")

    def matches(self, path: str) -> bool:
        """Rudimentary glob-or-substring match (no fs access)."""
        if not self.pattern:
            return False
        p = self.pattern
        if "*" not in p and "?" not in p:
            return p in path
        import fnmatch
        return fnmatch.fnmatch(path, p)


@dataclass(frozen=True)
class ReviewVerdict:
    """A recorded code review verdict plus eventual outcome for calibration."""

    id: str
    project_id: str
    pr_url: str
    reviewer_codename: str = ""
    decision: ReviewDecision = ReviewDecision.APPROVE
    severity: str = "low"  # low | medium | high | critical
    override_reason: str = ""  # e.g. "pragmatic approve"
    second_opinion: bool = False
    outcome: ReviewOutcome = ReviewOutcome.UNKNOWN
    outcome_note: str = ""
    created_at: datetime = field(default_factory=_now)
    outcome_at: datetime | None = None

    @staticmethod
    def new_id() -> str:
        return _rand("rev")
