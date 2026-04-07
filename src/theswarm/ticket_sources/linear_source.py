"""Linear adapter for the TicketSource protocol.

Requires LINEAR_API_KEY env var. Uses Linear's GraphQL API.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any

from theswarm.ticket_sources.protocol import Ticket, TicketStatus

log = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"

# Linear workflow state name → TicketStatus mapping (common defaults)
_STATE_TO_STATUS: dict[str, TicketStatus] = {
    "backlog": TicketStatus.BACKLOG,
    "todo": TicketStatus.READY,
    "in progress": TicketStatus.IN_PROGRESS,
    "in review": TicketStatus.REVIEW,
    "done": TicketStatus.DONE,
    "canceled": TicketStatus.DONE,
}


def _issue_to_ticket(node: dict) -> Ticket:
    state_name = node.get("state", {}).get("name", "").lower()
    status = _STATE_TO_STATUS.get(state_name, TicketStatus.BACKLOG)
    labels = [l["name"] for l in node.get("labels", {}).get("nodes", [])]
    assignee = node.get("assignee", {})

    return Ticket(
        id=node.get("identifier", node.get("id", "")),
        title=node.get("title", ""),
        body=node.get("description", ""),
        status=status,
        labels=labels,
        assignees=[assignee["name"]] if assignee else [],
        url=node.get("url", ""),
        source="linear",
        raw=node,
    )


class LinearTicketSource:
    """Linear adapter implementing TicketSource protocol."""

    def __init__(self, team_key: str, api_key: str = "") -> None:
        self._team_key = team_key
        self._api_key = api_key or os.environ.get("LINEAR_API_KEY", "")

    @property
    def source_name(self) -> str:
        return "linear"

    async def _query(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        import asyncio

        payload = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(
            LINEAR_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._api_key,
            },
        )
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=15)
        )
        return json.loads(resp.read())

    async def _get_issues_by_state(self, state_filter: str) -> list[Ticket]:
        gql = """
        query($teamKey: String!, $stateFilter: String!) {
            issues(filter: {
                team: { key: { eq: $teamKey } }
                state: { name: { eqIgnoreCase: $stateFilter } }
            }, first: 50) {
                nodes {
                    id identifier title description url
                    state { name }
                    labels { nodes { name } }
                    assignee { name }
                }
            }
        }
        """
        result = await self._query(gql, {"teamKey": self._team_key, "stateFilter": state_filter})
        nodes = result.get("data", {}).get("issues", {}).get("nodes", [])
        return [_issue_to_ticket(n) for n in nodes]

    async def get_backlog(self) -> list[Ticket]:
        return await self._get_issues_by_state("Backlog")

    async def get_ready(self) -> list[Ticket]:
        return await self._get_issues_by_state("Todo")

    async def get_in_progress(self) -> list[Ticket]:
        return await self._get_issues_by_state("In Progress")

    async def set_status(self, ticket_id: str, status: TicketStatus) -> None:
        state_names = {v: k for k, v in _STATE_TO_STATUS.items()}
        target_state = state_names.get(status, "backlog").title()

        gql = """
        mutation($issueId: String!, $stateId: String!) {
            issueUpdate(id: $issueId, input: { stateId: $stateId }) {
                success
            }
        }
        """
        # First, look up the workflow state ID
        states_gql = """
        query($teamKey: String!) {
            workflowStates(filter: { team: { key: { eq: $teamKey } } }) {
                nodes { id name }
            }
        }
        """
        result = await self._query(states_gql, {"teamKey": self._team_key})
        states = result.get("data", {}).get("workflowStates", {}).get("nodes", [])
        state_id = None
        for s in states:
            if s["name"].lower() == target_state.lower():
                state_id = s["id"]
                break

        if state_id:
            await self._query(gql, {"issueId": ticket_id, "stateId": state_id})

    async def create_ticket(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        parent_id: str | None = None,
    ) -> Ticket:
        gql = """
        mutation($teamKey: String!, $title: String!, $description: String, $parentId: String) {
            issueCreate(input: {
                teamId: $teamKey
                title: $title
                description: $description
                parentId: $parentId
            }) {
                success
                issue { id identifier title description url state { name } }
            }
        }
        """
        result = await self._query(gql, {
            "teamKey": self._team_key,
            "title": title,
            "description": body,
            "parentId": parent_id,
        })
        issue = result.get("data", {}).get("issueCreate", {}).get("issue", {})
        return _issue_to_ticket(issue)

    async def add_comment(self, ticket_id: str, body: str) -> None:
        gql = """
        mutation($issueId: String!, $body: String!) {
            commentCreate(input: { issueId: $issueId, body: $body }) {
                success
            }
        }
        """
        await self._query(gql, {"issueId": ticket_id, "body": body})
