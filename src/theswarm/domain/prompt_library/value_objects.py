"""Value objects for prompt library (Phase L)."""

from __future__ import annotations

from enum import Enum


class PromptAuditAction(str, Enum):
    """Action recorded in the prompt-library audit trail."""

    CREATE = "create"
    UPDATE = "update"
    DEPRECATE = "deprecate"
    RESTORE = "restore"
