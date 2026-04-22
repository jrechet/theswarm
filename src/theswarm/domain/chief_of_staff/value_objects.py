"""Value objects for the Chief of Staff bounded context (Phase K)."""

from __future__ import annotations

from enum import Enum


class RuleStatus(str, Enum):
    """Whether a routing rule is active."""

    ACTIVE = "active"
    DISABLED = "disabled"


class BudgetState(str, Enum):
    """Portfolio / project budget enforcement state."""

    ACTIVE = "active"  # within limits
    EXCEEDED = "exceeded"  # hard-stop; no new cycles
    PAUSED = "paused"  # manual pause (holidays, cost review)


class OnboardingStatus(str, Enum):
    """Progress of an onboarding step."""

    PENDING = "pending"
    COMPLETE = "complete"
    SKIPPED = "skipped"


class ArchiveReason(str, Enum):
    """Why a project was archived."""

    SHIPPED = "shipped"
    ABANDONED = "abandoned"
    MERGED = "merged"
    OTHER = "other"
