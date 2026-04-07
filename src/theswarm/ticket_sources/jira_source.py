"""Jira adapter for the TicketSource protocol.

Requires JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN env vars.
Uses Jira REST API v3.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.request
from typing import Any

from theswarm.ticket_sources.protocol import Ticket, TicketStatus

log = logging.getLogger(__name__)

_STATUS_TO_TICKET: dict[str, TicketStatus] = {
    "to do": TicketStatus.READY,
    "backlog": TicketStatus.BACKLOG,
    "in progress": TicketStatus.IN_PROGRESS,
    "in review": TicketStatus.REVIEW,
    "done": TicketStatus.DONE,
}


def _issue_to_ticket(issue: dict, base_url: str) -> Ticket:
    fields = issue.get("fields", {})
    status_name = fields.get("status", {}).get("name", "").lower()
    status = _STATUS_TO_TICKET.get(status_name, TicketStatus.BACKLOG)
    labels = fields.get("labels", [])
    assignee = fields.get("assignee") or {}

    return Ticket(
        id=issue["key"],
        title=fields.get("summary", ""),
        body=fields.get("description", "") or "",
        status=status,
        labels=labels,
        assignees=[assignee["displayName"]] if assignee.get("displayName") else [],
        url=f"{base_url}/browse/{issue['key']}",
        source="jira",
        raw=issue,
    )


class JiraTicketSource:
    """Jira adapter implementing TicketSource protocol."""

    def __init__(
        self,
        project_key: str,
        base_url: str = "",
        email: str = "",
        api_token: str = "",
    ) -> None:
        self._project = project_key
        self._base_url = (base_url or os.environ.get("JIRA_URL", "")).rstrip("/")
        self._email = email or os.environ.get("JIRA_EMAIL", "")
        self._token = api_token or os.environ.get("JIRA_API_TOKEN", "")

    @property
    def source_name(self) -> str:
        return "jira"

    def _auth_header(self) -> str:
        creds = f"{self._email}:{self._token}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        import asyncio

        url = f"{self._base_url}/rest/api/3/{path}"
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._auth_header(),
            },
        )
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=15)
        )
        return json.loads(resp.read())

    async def _search(self, jql: str, max_results: int = 50) -> list[Ticket]:
        result = await self._request("POST", "search", {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary", "description", "status", "labels", "assignee"],
        })
        issues = result.get("issues", [])
        return [_issue_to_ticket(i, self._base_url) for i in issues]

    async def get_backlog(self) -> list[Ticket]:
        return await self._search(f'project = {self._project} AND status = "Backlog"')

    async def get_ready(self) -> list[Ticket]:
        return await self._search(f'project = {self._project} AND status = "To Do"')

    async def get_in_progress(self) -> list[Ticket]:
        return await self._search(f'project = {self._project} AND status = "In Progress"')

    async def set_status(self, ticket_id: str, status: TicketStatus) -> None:
        # Jira requires transition IDs, not status names.
        # Get available transitions and find the matching one.
        result = await self._request("GET", f"issue/{ticket_id}/transitions")
        transitions = result.get("transitions", [])

        target_name_map = {
            TicketStatus.BACKLOG: "backlog",
            TicketStatus.READY: "to do",
            TicketStatus.IN_PROGRESS: "in progress",
            TicketStatus.REVIEW: "in review",
            TicketStatus.DONE: "done",
        }
        target = target_name_map.get(status, "").lower()

        for t in transitions:
            if t.get("to", {}).get("name", "").lower() == target:
                await self._request("POST", f"issue/{ticket_id}/transitions", {
                    "transition": {"id": t["id"]},
                })
                return

        log.warning("Jira: no transition to '%s' found for %s", target, ticket_id)

    async def create_ticket(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        parent_id: str | None = None,
    ) -> Ticket:
        fields: dict[str, Any] = {
            "project": {"key": self._project},
            "summary": title,
            "description": body,
            "issuetype": {"name": "Task" if not parent_id else "Sub-task"},
        }
        if labels:
            fields["labels"] = labels
        if parent_id:
            fields["parent"] = {"key": parent_id}

        result = await self._request("POST", "issue", {"fields": fields})
        issue_key = result.get("key", "")

        return Ticket(
            id=issue_key,
            title=title,
            body=body,
            status=TicketStatus.READY,
            labels=labels or [],
            url=f"{self._base_url}/browse/{issue_key}",
            source="jira",
        )

    async def add_comment(self, ticket_id: str, body: str) -> None:
        await self._request("POST", f"issue/{ticket_id}/comment", {
            "body": body,
        })
