"""Value objects for the Tickets bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TicketStatus(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    CANCELLED = "cancelled"


class TicketPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class TicketId:
    """Source-agnostic ticket identifier."""

    source: str    # "github", "jira", "linear", "gitlab"
    value: str     # "42", "PROJ-123", "abc-uuid"

    def __str__(self) -> str:
        return f"{self.source}:{self.value}"


@dataclass(frozen=True)
class Label:
    """A ticket label/tag."""

    name: str
    color: str = ""

    def __str__(self) -> str:
        return self.name
