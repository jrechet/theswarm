"""Value objects for the TechLead bounded context."""

from __future__ import annotations

from enum import Enum


class ADRStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class DebtSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DepSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    COMMENT = "comment"


class ReviewOutcome(str, Enum):
    """How the reviewed work played out after merge."""

    UNKNOWN = "unknown"
    CLEAN = "clean"  # merged and no follow-up defect
    PATCH_NEEDED = "patch_needed"  # small fix landed afterwards
    REVERTED = "reverted"  # had to be rolled back
