"""Value objects for the Security bounded context (Phase I)."""

from __future__ import annotations

from enum import Enum


class DataClass(str, Enum):
    """Data classification for inventory entries."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"
    PAYMENT = "payment"
    HEALTH = "health"


class FindingSeverity(str, Enum):
    """Severity tier for a security finding."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(str, Enum):
    """Lifecycle of a security finding."""

    OPEN = "open"
    TRIAGED = "triaged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class AuthZEffect(str, Enum):
    """Whether an AuthZ rule allows or denies."""

    ALLOW = "allow"
    DENY = "deny"
