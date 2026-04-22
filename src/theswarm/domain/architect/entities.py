"""Entities for the Architect bounded context (Phase K)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.architect.value_objects import (
    ADRStatus,
    BriefScope,
    RuleSeverity,
)


@dataclass(frozen=True)
class PavedRoadRule:
    """A portfolio-wide convention. Advisory by default, required when strict."""

    id: str
    name: str
    rule: str  # the actual rule text
    rationale: str = ""
    severity: RuleSeverity = RuleSeverity.ADVISORY
    tags: tuple[str, ...] = field(default_factory=tuple)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_blocking(self) -> bool:
        return self.severity == RuleSeverity.REQUIRED


@dataclass(frozen=True)
class PortfolioADR:
    """An architectural decision, portfolio-scoped or project-scoped."""

    id: str
    title: str
    status: ADRStatus = ADRStatus.PROPOSED
    context: str = ""
    decision: str = ""
    consequences: str = ""
    project_id: str = ""  # empty = portfolio-wide
    supersedes: str = ""  # id of prior ADR when SUPERSEDED
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_portfolio_wide(self) -> bool:
        return self.project_id == ""

    @property
    def is_active(self) -> bool:
        return self.status == ADRStatus.ACCEPTED


@dataclass(frozen=True)
class DirectionBrief:
    """A forward-looking brief setting direction for a period."""

    id: str
    title: str
    scope: BriefScope = BriefScope.PORTFOLIO
    project_id: str = ""  # required when scope == PROJECT
    period: str = ""  # e.g. "2026-Q2"
    author: str = ""
    focus_areas: tuple[str, ...] = field(default_factory=tuple)
    risks: tuple[str, ...] = field(default_factory=tuple)
    narrative: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_project_scoped(self) -> bool:
        return self.scope == BriefScope.PROJECT
