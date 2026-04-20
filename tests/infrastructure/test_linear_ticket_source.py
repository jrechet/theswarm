"""Sprint F P2 — LinearTicketSource tests mirroring the GitHubTicketSource suite."""

from __future__ import annotations

from theswarm.domain.tickets.value_objects import TicketPriority, TicketStatus
from theswarm.infrastructure.tickets.linear_ticket_source import (
    LinearTicketSource,
    _node_to_ticket,
)


class FakeLinearClient:
    """Deterministic stand-in for the Linear GraphQL client."""

    def __init__(self, handlers: dict | None = None) -> None:
        self._handlers: dict = handlers or {}
        self.calls: list[tuple[str, dict]] = []

    async def query(self, document: str, variables: dict) -> dict:
        self.calls.append((document, variables))
        for fragment, fn in self._handlers.items():
            if fragment in document:
                return fn(variables)
        return {"data": {}}


def _issue_node(
    ident: str = "ABC-1", title: str = "t", state: str = "Backlog",
    priority: int = 0, labels: list[str] | None = None,
) -> dict:
    return {
        "id": f"uuid-{ident}",
        "identifier": ident,
        "title": title,
        "description": "",
        "priority": priority,
        "url": f"https://linear.app/team/issue/{ident}",
        "state": {"name": state},
        "assignee": None,
        "labels": {"nodes": [{"name": n} for n in (labels or [])]},
    }


class TestNodeToTicket:
    def test_basic_fields(self):
        t = _node_to_ticket(_issue_node("ABC-42", "Hello", state="Backlog"))
        assert t.id.source == "linear"
        assert t.id.value == "ABC-42"
        assert t.title == "Hello"
        assert t.status == TicketStatus.BACKLOG

    def test_todo_maps_to_ready(self):
        t = _node_to_ticket(_issue_node(state="Todo"))
        assert t.status == TicketStatus.READY

    def test_in_progress(self):
        t = _node_to_ticket(_issue_node(state="In Progress"))
        assert t.status == TicketStatus.IN_PROGRESS

    def test_in_review(self):
        t = _node_to_ticket(_issue_node(state="In Review"))
        assert t.status == TicketStatus.REVIEW

    def test_priority_mapping(self):
        assert _node_to_ticket(_issue_node(priority=1)).priority == TicketPriority.CRITICAL
        assert _node_to_ticket(_issue_node(priority=2)).priority == TicketPriority.HIGH
        assert _node_to_ticket(_issue_node(priority=3)).priority == TicketPriority.MEDIUM
        assert _node_to_ticket(_issue_node(priority=4)).priority == TicketPriority.LOW
        assert _node_to_ticket(_issue_node(priority=0)).priority == TicketPriority.NONE

    def test_labels(self):
        t = _node_to_ticket(_issue_node(labels=["bug", "frontend"]))
        assert "bug" in t.label_names
        assert "frontend" in t.label_names

    def test_missing_state(self):
        t = _node_to_ticket({"id": "x", "identifier": "X-1", "title": "t"})
        assert t.status == TicketStatus.BACKLOG


class TestLinearTicketSource:
    def _source(self, handlers: dict) -> tuple[LinearTicketSource, FakeLinearClient]:
        client = FakeLinearClient(handlers)
        return LinearTicketSource(client, team_id="team-uuid"), client

    async def test_get_backlog_filters_by_state(self):
        def on_list(vars):
            assert vars["stateName"] == "Backlog"
            return {"data": {"issues": {"nodes": [_issue_node("A-1", state="Backlog")]}}}

        source, client = self._source({"query ListIssues": on_list})
        tickets = await source.get_backlog()
        assert len(tickets) == 1
        assert tickets[0].status == TicketStatus.BACKLOG

    async def test_get_ready_uses_todo_state(self):
        def on_list(vars):
            assert vars["stateName"] == "Todo"
            return {"data": {"issues": {"nodes": [_issue_node("A-2", state="Todo")]}}}

        source, _ = self._source({"query ListIssues": on_list})
        tickets = await source.get_ready()
        assert tickets[0].status == TicketStatus.READY

    async def test_get_in_progress(self):
        def on_list(vars):
            assert vars["stateName"] == "In Progress"
            return {"data": {"issues": {"nodes": [_issue_node(state="In Progress")]}}}

        source, _ = self._source({"query ListIssues": on_list})
        tickets = await source.get_in_progress()
        assert len(tickets) == 1

    async def test_transition_looks_up_state_id_then_updates(self):
        calls: list[str] = []

        def on_states(vars):
            calls.append("states")
            return {"data": {"workflowStates": {"nodes": [
                {"id": "todo-id", "name": "Todo"},
                {"id": "done-id", "name": "Done"},
            ]}}}

        def on_update(vars):
            calls.append("update")
            assert vars == {"id": "ABC-5", "stateId": "todo-id"}
            return {"data": {"issueUpdate": {"success": True, "issue": {}}}}

        source, _ = self._source({
            "query WorkflowStates": on_states,
            "mutation UpdateIssueState": on_update,
        })
        await source.transition("ABC-5", TicketStatus.READY)
        assert calls == ["states", "update"]

    async def test_transition_skips_when_state_not_found(self):
        def on_states(vars):
            return {"data": {"workflowStates": {"nodes": []}}}

        source, client = self._source({"query WorkflowStates": on_states})
        await source.transition("ABC-5", TicketStatus.READY)
        # Only the states lookup should have been called, no update
        assert len(client.calls) == 1

    async def test_create_with_labels_looks_up_label_ids(self):
        def on_labels(vars):
            return {"data": {"issueLabels": {"nodes": [
                {"id": "l-bug", "name": "bug"},
                {"id": "l-fe", "name": "frontend"},
                {"id": "l-be", "name": "backend"},
            ]}}}

        def on_create(vars):
            assert sorted(vars["labelIds"]) == ["l-bug", "l-fe"]
            return {"data": {"issueCreate": {"success": True, "issue": _issue_node(
                ident="NEW-1", title=vars["title"], labels=["bug", "frontend"],
            )}}}

        source, _ = self._source({
            "query ListLabels": on_labels,
            "mutation CreateIssue": on_create,
        })
        ticket = await source.create("Add login", "desc", labels=["bug", "frontend"])
        assert ticket.title == "Add login"
        assert ticket.id.value == "NEW-1"
        assert "bug" in ticket.label_names

    async def test_create_without_labels_skips_label_lookup(self):
        calls: list[str] = []

        def on_create(vars):
            calls.append("create")
            assert vars["labelIds"] == []
            return {"data": {"issueCreate": {"issue": _issue_node("NEW-2")}}}

        source, _ = self._source({"mutation CreateIssue": on_create})
        await source.create("t", "b")
        assert calls == ["create"]

    async def test_empty_backlog(self):
        def on_list(vars):
            return {"data": {"issues": {"nodes": []}}}

        source, _ = self._source({"query ListIssues": on_list})
        assert await source.get_backlog() == []

    async def test_custom_state_map_overrides_defaults(self):
        captured: list[str] = []

        def on_list(vars):
            captured.append(vars["stateName"])
            return {"data": {"issues": {"nodes": []}}}

        client = FakeLinearClient({"query ListIssues": on_list})
        source = LinearTicketSource(
            client, team_id="t",
            state_map={TicketStatus.READY: "Up Next"},
        )
        await source.get_ready()
        assert captured == ["Up Next"]
