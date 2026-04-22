"""Value objects for the Release bounded context (Phase J)."""

from __future__ import annotations

from enum import Enum


class ReleaseStatus(str, Enum):
    """Where a release stands."""

    DRAFT = "draft"
    RELEASED = "released"
    ROLLED_BACK = "rolled_back"


class FlagState(str, Enum):
    """Feature-flag lifecycle state."""

    ACTIVE = "active"
    STALE = "stale"  # older than cleanup window, candidate for removal
    ARCHIVED = "archived"  # removed from code, kept for audit


class RollbackStatus(str, Enum):
    """Where a rollback action stands."""

    READY = "ready"  # revert link prepared
    EXECUTED = "executed"
    OBSOLETE = "obsolete"  # superseded by a newer release
