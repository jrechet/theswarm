"""GitHub Issues adapter for the TicketSource protocol."""

from __future__ import annotations

import logging

from theswarm.ticket_sources.protocol import Ticket, TicketSource, TicketStatus

log = logging.getLogger(__name__)

# Map GitHub labels to TicketStatus
_LABEL_TO_STATUS: dict[str, TicketStatus] = {
    "status:backlog": TicketStatus.BACKLOG,
    "status:ready": TicketStatus.READY,
    "status:in-progress": TicketStatus.IN_PROGRESS,
    "status:review": TicketStatus.REVIEW,
    "status:done": TicketStatus.DONE,
}

# Reverse map for setting labels
_STATUS_TO_LABEL: dict[TicketStatus, str] = {v: k for k, v in _LABEL_TO_STATUS.items()}


def _issue_to_ticket(issue: dict) -> Ticket:
    """Convert a GitHubClient issue dict to a Ticket."""
    labels = [l if isinstance(l, str) else l.get("name", "") for l in issue.get("labels", [])]

    # Determine status from labels
    status = TicketStatus.BACKLOG
    for label in labels:
        if label in _LABEL_TO_STATUS:
            status = _LABEL_TO_STATUS[label]
            break

    return Ticket(
        id=str(issue["number"]),
        title=issue["title"],
        body=issue.get("body", ""),
        status=status,
        labels=labels,
        assignees=issue.get("assignees", []),
        url=issue.get("url", ""),
        source="github",
        raw=issue,
    )


class GitHubTicketSource:
    """GitHub Issues adapter implementing TicketSource protocol."""

    def __init__(self, github_client) -> None:
        self._gh = github_client

    @property
    def source_name(self) -> str:
        return "github"

    async def get_backlog(self) -> list[Ticket]:
        issues = await self._gh.get_issues(labels=["status:backlog"])
        return [_issue_to_ticket(i) for i in issues]

    async def get_ready(self) -> list[Ticket]:
        issues = await self._gh.get_issues(labels=["status:ready"])
        return [_issue_to_ticket(i) for i in issues]

    async def get_in_progress(self) -> list[Ticket]:
        issues = await self._gh.get_issues(labels=["status:in-progress"])
        return [_issue_to_ticket(i) for i in issues]

    async def set_status(self, ticket_id: str, status: TicketStatus) -> None:
        issue_number = int(ticket_id)
        new_label = _STATUS_TO_LABEL.get(status)

        # Remove all status: labels first
        for label in _LABEL_TO_STATUS:
            try:
                await self._gh.remove_label(issue_number, label)
            except Exception:
                pass

        # Add the new status label
        if new_label:
            await self._gh.add_labels(issue_number, [new_label])

    async def create_ticket(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        parent_id: str | None = None,
    ) -> Ticket:
        if parent_id:
            body += f"\n\nParent: #{parent_id}"

        issue = await self._gh.create_issue(
            title=title,
            body=body,
            labels=labels or ["role:dev", "status:ready"],
        )
        return _issue_to_ticket(issue)

    async def add_comment(self, ticket_id: str, body: str) -> None:
        await self._gh.add_comment(int(ticket_id), body)
