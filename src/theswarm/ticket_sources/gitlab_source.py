"""GitLab Issues adapter for the TicketSource protocol.

Requires GITLAB_URL and GITLAB_TOKEN env vars.
Uses GitLab REST API v4.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any
from urllib.parse import quote

from theswarm.ticket_sources.protocol import Ticket, TicketStatus

log = logging.getLogger(__name__)

_LABEL_TO_STATUS: dict[str, TicketStatus] = {
    "status:backlog": TicketStatus.BACKLOG,
    "status:ready": TicketStatus.READY,
    "status:in-progress": TicketStatus.IN_PROGRESS,
    "status:review": TicketStatus.REVIEW,
    "status:done": TicketStatus.DONE,
}

_STATUS_TO_LABEL: dict[TicketStatus, str] = {v: k for k, v in _LABEL_TO_STATUS.items()}


def _issue_to_ticket(issue: dict, base_url: str) -> Ticket:
    labels = issue.get("labels", [])
    status = TicketStatus.BACKLOG
    for label in labels:
        if label in _LABEL_TO_STATUS:
            status = _LABEL_TO_STATUS[label]
            break

    assignees = [a.get("username", "") for a in issue.get("assignees", [])]

    return Ticket(
        id=str(issue["iid"]),
        title=issue.get("title", ""),
        body=issue.get("description", "") or "",
        status=status,
        labels=labels,
        assignees=assignees,
        url=issue.get("web_url", ""),
        source="gitlab",
        raw=issue,
    )


class GitLabTicketSource:
    """GitLab Issues adapter implementing TicketSource protocol."""

    def __init__(
        self,
        project_path: str,
        base_url: str = "",
        token: str = "",
    ) -> None:
        self._project_path = project_path
        self._base_url = (base_url or os.environ.get("GITLAB_URL", "https://gitlab.com")).rstrip("/")
        self._token = token or os.environ.get("GITLAB_TOKEN", "")
        self._project_id = quote(project_path, safe="")

    @property
    def source_name(self) -> str:
        return "gitlab"

    async def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        import asyncio

        url = f"{self._base_url}/api/v4/{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Content-Type": "application/json",
                "PRIVATE-TOKEN": self._token,
            },
        )
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=15)
        )
        return json.loads(resp.read())

    async def _get_by_label(self, label: str) -> list[Ticket]:
        issues = await self._request(
            "GET",
            f"projects/{self._project_id}/issues?labels={label}&state=opened&per_page=50",
        )
        return [_issue_to_ticket(i, self._base_url) for i in issues]

    async def get_backlog(self) -> list[Ticket]:
        return await self._get_by_label("status:backlog")

    async def get_ready(self) -> list[Ticket]:
        return await self._get_by_label("status:ready")

    async def get_in_progress(self) -> list[Ticket]:
        return await self._get_by_label("status:in-progress")

    async def set_status(self, ticket_id: str, status: TicketStatus) -> None:
        # Get current labels, swap the status label
        issue = await self._request(
            "GET", f"projects/{self._project_id}/issues/{ticket_id}"
        )
        current_labels = issue.get("labels", [])

        # Remove old status labels, add new one
        new_labels = [l for l in current_labels if l not in _LABEL_TO_STATUS]
        new_label = _STATUS_TO_LABEL.get(status)
        if new_label:
            new_labels.append(new_label)

        await self._request(
            "PUT",
            f"projects/{self._project_id}/issues/{ticket_id}",
            {"labels": ",".join(new_labels)},
        )

    async def create_ticket(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        parent_id: str | None = None,
    ) -> Ticket:
        if parent_id:
            body += f"\n\nRelated to #{parent_id}"

        payload: dict[str, Any] = {
            "title": title,
            "description": body,
        }
        if labels:
            payload["labels"] = ",".join(labels)

        issue = await self._request(
            "POST", f"projects/{self._project_id}/issues", payload
        )
        return _issue_to_ticket(issue, self._base_url)

    async def add_comment(self, ticket_id: str, body: str) -> None:
        await self._request(
            "POST",
            f"projects/{self._project_id}/issues/{ticket_id}/notes",
            {"body": body},
        )
