"""Pluggable ticket sources — abstract interface + platform adapters.

TicketSource is the protocol that all ticket adapters implement.
Each adapter translates platform-specific ticket semantics (GitHub Issues,
Linear issues, Jira tickets, GitLab issues) into a common Ticket model.
"""

from theswarm.ticket_sources.protocol import Ticket, TicketSource, TicketStatus
from theswarm.ticket_sources.github_source import GitHubTicketSource

__all__ = [
    "Ticket",
    "TicketSource",
    "TicketStatus",
    "GitHubTicketSource",
]
