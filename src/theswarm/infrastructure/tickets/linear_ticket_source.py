"""Linear adapter implementing the TicketSource port.

Talks to the Linear GraphQL API via a tiny injected client. The client
only needs one method — ``query(document, variables) -> dict`` — which
keeps the adapter trivial to fake in tests and decoupled from any
specific HTTP library.

Workflow state names are team-specific in Linear, so we accept a
``state_map: dict[TicketStatus, str]`` at construction time. The defaults
match the common out-of-the-box names (Backlog / Todo / In Progress /
In Review / Done) and can be overridden per project.
"""

from __future__ import annotations

from typing import Any, Protocol

from theswarm.domain.tickets.entities import Ticket
from theswarm.domain.tickets.value_objects import (
    Label,
    TicketId,
    TicketPriority,
    TicketStatus,
)


_DEFAULT_STATE_MAP: dict[TicketStatus, str] = {
    TicketStatus.BACKLOG: "Backlog",
    TicketStatus.READY: "Todo",
    TicketStatus.IN_PROGRESS: "In Progress",
    TicketStatus.REVIEW: "In Review",
    TicketStatus.DONE: "Done",
    TicketStatus.CANCELLED: "Cancelled",
}


# Linear priority: 0=no priority, 1=urgent, 2=high, 3=medium, 4=low
_LINEAR_PRIORITY_MAP: dict[int, TicketPriority] = {
    0: TicketPriority.NONE,
    1: TicketPriority.CRITICAL,
    2: TicketPriority.HIGH,
    3: TicketPriority.MEDIUM,
    4: TicketPriority.LOW,
}


class LinearClient(Protocol):
    async def query(self, document: str, variables: dict[str, Any]) -> dict[str, Any]: ...


def _node_to_ticket(node: dict) -> Ticket:
    raw_labels = node.get("labels", {}).get("nodes", []) if isinstance(node.get("labels"), dict) else node.get("labels", [])
    label_names = [lb.get("name", "") for lb in raw_labels if isinstance(lb, dict)]

    state_name = ""
    state = node.get("state", {})
    if isinstance(state, dict):
        state_name = state.get("name", "")

    status = TicketStatus.BACKLOG
    for enum_value, linear_name in _DEFAULT_STATE_MAP.items():
        if state_name == linear_name:
            status = enum_value
            break

    priority_raw = node.get("priority")
    priority = TicketPriority.NONE
    if isinstance(priority_raw, int):
        priority = _LINEAR_PRIORITY_MAP.get(priority_raw, TicketPriority.NONE)

    assignee = node.get("assignee") or {}
    assignee_name = assignee.get("name", "") if isinstance(assignee, dict) else ""

    return Ticket(
        id=TicketId(source="linear", value=node.get("identifier", "") or node.get("id", "")),
        title=node.get("title", ""),
        body=node.get("description", "") or "",
        status=status,
        priority=priority,
        labels=tuple(Label(name=n) for n in label_names if n),
        assignee=assignee_name,
        url=node.get("url", ""),
    )


_LIST_ISSUES_QUERY = """
query ListIssues($teamId: String!, $stateName: String!) {
  issues(filter: {team: {id: {eq: $teamId}}, state: {name: {eq: $stateName}}}) {
    nodes {
      id
      identifier
      title
      description
      priority
      url
      state { name }
      assignee { name }
      labels { nodes { name } }
    }
  }
}
"""

_LIST_WORKFLOW_STATES_QUERY = """
query WorkflowStates($teamId: String!) {
  workflowStates(filter: {team: {id: {eq: $teamId}}}) {
    nodes { id name }
  }
}
"""

_UPDATE_ISSUE_STATE_QUERY = """
mutation UpdateIssueState($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: {stateId: $stateId}) {
    success
    issue {
      id
      identifier
      title
      description
      priority
      url
      state { name }
      assignee { name }
      labels { nodes { name } }
    }
  }
}
"""

_CREATE_ISSUE_QUERY = """
mutation CreateIssue($teamId: String!, $title: String!, $description: String!, $labelIds: [String!]) {
  issueCreate(input: {teamId: $teamId, title: $title, description: $description, labelIds: $labelIds}) {
    success
    issue {
      id
      identifier
      title
      description
      priority
      url
      state { name }
      assignee { name }
      labels { nodes { name } }
    }
  }
}
"""

_LIST_LABELS_QUERY = """
query ListLabels($teamId: String!) {
  issueLabels(filter: {team: {id: {eq: $teamId}}}) {
    nodes { id name }
  }
}
"""


class LinearTicketSource:
    """TicketSource adapter for Linear.app."""

    def __init__(
        self,
        client: LinearClient,
        team_id: str,
        state_map: dict[TicketStatus, str] | None = None,
    ) -> None:
        self._client = client
        self._team_id = team_id
        self._state_map = dict(_DEFAULT_STATE_MAP)
        if state_map:
            self._state_map.update(state_map)

    async def _list_by_state(self, status: TicketStatus) -> list[Ticket]:
        state_name = self._state_map.get(status, "")
        if not state_name:
            return []
        result = await self._client.query(
            _LIST_ISSUES_QUERY,
            {"teamId": self._team_id, "stateName": state_name},
        )
        nodes = result.get("data", {}).get("issues", {}).get("nodes", [])
        return [_node_to_ticket(n) for n in nodes]

    async def get_backlog(self) -> list[Ticket]:
        return await self._list_by_state(TicketStatus.BACKLOG)

    async def get_ready(self) -> list[Ticket]:
        return await self._list_by_state(TicketStatus.READY)

    async def get_in_progress(self) -> list[Ticket]:
        return await self._list_by_state(TicketStatus.IN_PROGRESS)

    async def transition(self, ticket_id: str, to_status: TicketStatus) -> None:
        state_name = self._state_map.get(to_status)
        if state_name is None:
            return

        states = await self._client.query(
            _LIST_WORKFLOW_STATES_QUERY, {"teamId": self._team_id},
        )
        nodes = states.get("data", {}).get("workflowStates", {}).get("nodes", [])
        state_id = next((n["id"] for n in nodes if n.get("name") == state_name), None)
        if state_id is None:
            return

        await self._client.query(
            _UPDATE_ISSUE_STATE_QUERY,
            {"id": ticket_id, "stateId": state_id},
        )

    async def create(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> Ticket:
        label_ids: list[str] = []
        if labels:
            resp = await self._client.query(
                _LIST_LABELS_QUERY, {"teamId": self._team_id},
            )
            nodes = resp.get("data", {}).get("issueLabels", {}).get("nodes", [])
            wanted = set(labels)
            label_ids = [n["id"] for n in nodes if n.get("name") in wanted]

        result = await self._client.query(
            _CREATE_ISSUE_QUERY,
            {
                "teamId": self._team_id,
                "title": title,
                "description": body,
                "labelIds": label_ids,
            },
        )
        issue = (
            result.get("data", {}).get("issueCreate", {}).get("issue") or {}
        )
        return _node_to_ticket(issue)
