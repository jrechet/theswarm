"""Entities for the Tickets bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.tickets.value_objects import Label, TicketId, TicketPriority, TicketStatus


@dataclass(frozen=True)
class Ticket:
    """A work item from any ticket source."""

    id: TicketId
    title: str
    body: str = ""
    status: TicketStatus = TicketStatus.BACKLOG
    priority: TicketPriority = TicketPriority.NONE
    labels: tuple[Label, ...] = ()
    assignee: str = ""
    url: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None

    @property
    def label_names(self) -> list[str]:
        return [l.name for l in self.labels]

    def with_status(self, status: TicketStatus) -> Ticket:
        return Ticket(
            id=self.id,
            title=self.title,
            body=self.body,
            status=status,
            priority=self.priority,
            labels=self.labels,
            assignee=self.assignee,
            url=self.url,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )

    def with_labels(self, labels: tuple[Label, ...]) -> Ticket:
        return Ticket(
            id=self.id,
            title=self.title,
            body=self.body,
            status=self.status,
            priority=self.priority,
            labels=labels,
            assignee=self.assignee,
            url=self.url,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )
