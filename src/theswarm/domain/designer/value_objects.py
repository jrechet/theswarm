"""Value objects for the Designer bounded context (Phase H)."""

from __future__ import annotations

from enum import Enum


class TokenKind(str, Enum):
    """What kind of design token is captured."""

    __test__ = False  # pytest: not a test class

    COLOR = "color"
    TYPOGRAPHY = "typography"
    SPACING = "spacing"
    MOTION = "motion"
    RADIUS = "radius"
    SHADOW = "shadow"
    OTHER = "other"


class ComponentStatus(str, Enum):
    """Where a component sits in the promotion pipeline."""

    PROPOSED = "proposed"
    SHARED = "shared"
    LEGACY = "legacy"
    DEPRECATED = "deprecated"


class BriefStatus(str, Enum):
    """Lifecycle of a design brief attached to a story."""

    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class CheckStatus(str, Enum):
    """Outcome of a visual regression / anti-template check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"
