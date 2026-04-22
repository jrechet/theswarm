"""Entities for the Chief of Staff bounded context (Phase K)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.chief_of_staff.value_objects import (
    ArchiveReason,
    BudgetState,
    OnboardingStatus,
    RuleStatus,
)


@dataclass(frozen=True)
class RoutingRule:
    """Keyword-based rule mapping incoming chat to a role (+ codename)."""

    id: str
    pattern: str  # matched against message text (case-insensitive)
    target_role: str  # po | techlead | dev | qa | scout | ...
    target_codename: str = ""  # optional override when more than one
    priority: int = 100  # lower fires first
    status: RuleStatus = RuleStatus.ACTIVE
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_enabled(self) -> bool:
        return self.status == RuleStatus.ACTIVE


@dataclass(frozen=True)
class BudgetPolicy:
    """Portfolio-wide (project_id="") or per-project budget policy."""

    id: str
    project_id: str = ""  # empty = portfolio-wide
    daily_tokens_limit: int = 0  # 0 = no cap
    daily_cost_usd_limit: float = 0.0  # 0 = no cap
    state: BudgetState = BudgetState.ACTIVE
    note: str = ""
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
    def blocks_cycles(self) -> bool:
        return self.state in (BudgetState.EXCEEDED, BudgetState.PAUSED)


@dataclass(frozen=True)
class OnboardingStep:
    """One step of the new-project onboarding wizard."""

    id: str
    project_id: str
    step_name: str  # create_roster | assign_codenames | seed_memory | ...
    order: int = 0
    status: OnboardingStatus = OnboardingStatus.PENDING
    note: str = ""
    completed_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_done(self) -> bool:
        return self.status in (
            OnboardingStatus.COMPLETE, OnboardingStatus.SKIPPED,
        )


@dataclass(frozen=True)
class ArchivedProject:
    """Record that a project was archived (memory frozen, dashboards off)."""

    id: str
    project_id: str
    reason: ArchiveReason = ArchiveReason.OTHER
    memory_frozen: bool = True
    export_path: str = ""
    note: str = ""
    archived_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
