"""Value objects for product intelligence."""

from __future__ import annotations

from enum import Enum


class ProposalStatus(str, Enum):
    """Lifecycle of a Proposal in the PO inbox.

    ``PROPOSED`` → human review pending.
    ``APPROVED`` → convert to backlog story.
    ``DEFERRED`` → keep for later; do not act.
    ``REJECTED`` → drop, record rationale.
    ``ASKED`` → PO needs a human answer before deciding.
    """

    PROPOSED = "proposed"
    APPROVED = "approved"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    ASKED = "asked"


class SignalKind(str, Enum):
    """Where a signal came from."""

    COMPETITOR = "competitor"
    ECOSYSTEM = "ecosystem"
    CUSTOMER = "customer"
    INTERNAL = "internal"


class SignalSeverity(str, Enum):
    """How a signal should be prioritised."""

    THREAT = "threat"
    OPPORTUNITY = "opportunity"
    NOISE = "noise"
    INFO = "info"


class InsightKind(str, Enum):
    """Category of insight surfaced in the weekly digest."""

    COMPETITOR_MOVE = "competitor_move"
    TREND = "trend"
    USER_REQUEST = "user_request"
    RISK = "risk"
    OUTCOME = "outcome"


class PolicyDecision(str, Enum):
    """Result of a policy check against a story / proposal."""

    ALLOW = "allow"
    BLOCK = "block"
    REVIEW = "review"
