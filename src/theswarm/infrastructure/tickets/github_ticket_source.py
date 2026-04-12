"""GitHub Issues adapter implementing the TicketSource port."""

from __future__ import annotations

from theswarm.domain.agents.ports import VCSPort
from theswarm.domain.tickets.entities import Ticket
from theswarm.domain.tickets.value_objects import Label, TicketId, TicketPriority, TicketStatus

# GitHub label → domain status mapping
_LABEL_STATUS_MAP: dict[str, TicketStatus] = {
    "status:backlog": TicketStatus.BACKLOG,
    "status:ready": TicketStatus.READY,
    "status:in-progress": TicketStatus.IN_PROGRESS,
    "status:review": TicketStatus.REVIEW,
    "status:done": TicketStatus.DONE,
}

_STATUS_LABEL_MAP: dict[TicketStatus, str] = {v: k for k, v in _LABEL_STATUS_MAP.items()}

_PRIORITY_LABEL_MAP: dict[str, TicketPriority] = {
    "priority:critical": TicketPriority.CRITICAL,
    "priority:high": TicketPriority.HIGH,
    "priority:medium": TicketPriority.MEDIUM,
    "priority:low": TicketPriority.LOW,
}


def _issue_to_ticket(issue: dict) -> Ticket:
    """Convert a GitHub issue dict to a domain Ticket."""
    raw_labels = issue.get("labels", [])
    label_names: list[str] = []
    for lb in raw_labels:
        if isinstance(lb, dict):
            label_names.append(lb.get("name", ""))
        else:
            label_names.append(str(lb))

    status = TicketStatus.BACKLOG
    for lname in label_names:
        if lname in _LABEL_STATUS_MAP:
            status = _LABEL_STATUS_MAP[lname]
            break

    priority = TicketPriority.NONE
    for lname in label_names:
        if lname in _PRIORITY_LABEL_MAP:
            priority = _PRIORITY_LABEL_MAP[lname]
            break

    return Ticket(
        id=TicketId(source="github", value=str(issue.get("number", ""))),
        title=issue.get("title", ""),
        body=issue.get("body", "") or "",
        status=status,
        priority=priority,
        labels=tuple(Label(name=n) for n in label_names),
        assignee=issue.get("assignee", "") or "",
        url=issue.get("html_url", "") or issue.get("url", ""),
    )


class GitHubTicketSource:
    """Adapts VCSPort (GitHub issues) to the TicketSource protocol."""

    def __init__(self, vcs: VCSPort) -> None:
        self._vcs = vcs

    async def get_backlog(self) -> list[Ticket]:
        issues = await self._vcs.get_issues(labels=["status:backlog"])
        return [_issue_to_ticket(i) for i in issues]

    async def get_in_progress(self) -> list[Ticket]:
        issues = await self._vcs.get_issues(labels=["status:in-progress"])
        return [_issue_to_ticket(i) for i in issues]

    async def get_ready(self) -> list[Ticket]:
        issues = await self._vcs.get_issues(labels=["status:ready"])
        return [_issue_to_ticket(i) for i in issues]

    async def transition(self, ticket_id: str, to_status: TicketStatus) -> None:
        number = int(ticket_id)
        new_label = _STATUS_LABEL_MAP.get(to_status)
        if new_label is None:
            return

        # Get current labels, remove old status labels, add new one
        issues = await self._vcs.get_issues(state="open")
        target = None
        for issue in issues:
            if issue.get("number") == number:
                target = issue
                break

        if target is None:
            issues = await self._vcs.get_issues(state="closed")
            for issue in issues:
                if issue.get("number") == number:
                    target = issue
                    break

        if target is None:
            return

        raw_labels = target.get("labels", [])
        current_labels: list[str] = []
        for lb in raw_labels:
            name = lb.get("name", "") if isinstance(lb, dict) else str(lb)
            if name and not name.startswith("status:"):
                current_labels.append(name)

        current_labels.append(new_label)
        await self._vcs.update_issue(number, labels=current_labels)

    async def create(
        self, title: str, body: str, labels: list[str] | None = None,
    ) -> Ticket:
        issue = await self._vcs.create_issue(title=title, body=body, labels=labels)
        return _issue_to_ticket(issue)
