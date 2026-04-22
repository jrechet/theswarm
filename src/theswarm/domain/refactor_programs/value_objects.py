"""Value objects for refactor programs (Phase L)."""

from __future__ import annotations

from enum import Enum


class RefactorProgramStatus(str, Enum):
    """Lifecycle state of a cross-project refactor program."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
