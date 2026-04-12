"""Ports for the Tickets bounded context."""

from __future__ import annotations

from typing import Protocol

from theswarm.domain.tickets.entities import Ticket
from theswarm.domain.tickets.value_objects import TicketStatus


class TicketSource(Protocol):
    """Read/write tickets from any source: GitHub, Jira, Linear, GitLab."""

    async def get_backlog(self) -> list[Ticket]: ...
    async def get_in_progress(self) -> list[Ticket]: ...
    async def get_ready(self) -> list[Ticket]: ...
    async def transition(self, ticket_id: str, to_status: TicketStatus) -> None: ...
    async def create(self, title: str, body: str, labels: list[str] | None = None) -> Ticket: ...
