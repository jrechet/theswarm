"""TicketSource protocol — the interface all ticket adapters implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class TicketStatus(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


@dataclass
class Ticket:
    """Platform-agnostic ticket representation."""
    id: str                          # platform-specific ID (e.g., "42" for GitHub, "LIN-123" for Linear)
    title: str
    body: str = ""
    status: TicketStatus = TicketStatus.BACKLOG
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    url: str = ""
    source: str = ""                 # "github", "linear", "jira", "gitlab"
    raw: dict = field(default_factory=dict)  # original platform data


@runtime_checkable
class TicketSource(Protocol):
    """Protocol for ticket source adapters.

    Each method translates platform concepts to/from the Ticket model.
    """

    @property
    def source_name(self) -> str:
        """Platform identifier (e.g., 'github', 'linear')."""
        ...

    async def get_backlog(self) -> list[Ticket]:
        """Fetch tickets in backlog/todo state."""
        ...

    async def get_ready(self) -> list[Ticket]:
        """Fetch tickets ready for development."""
        ...

    async def get_in_progress(self) -> list[Ticket]:
        """Fetch tickets currently being worked on."""
        ...

    async def set_status(self, ticket_id: str, status: TicketStatus) -> None:
        """Update a ticket's status."""
        ...

    async def create_ticket(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        parent_id: str | None = None,
    ) -> Ticket:
        """Create a new ticket (e.g., sub-task from story breakdown)."""
        ...

    async def add_comment(self, ticket_id: str, body: str) -> None:
        """Add a comment to a ticket."""
        ...
