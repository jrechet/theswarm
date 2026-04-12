"""Tests for infrastructure/tickets/github_ticket_source.py."""

from __future__ import annotations

import pytest

from theswarm.domain.tickets.value_objects import TicketStatus
from theswarm.infrastructure.tickets.github_ticket_source import (
    GitHubTicketSource,
    _issue_to_ticket,
)


# ── Unit: _issue_to_ticket ───────────────────────────────────────


class TestIssueToTicket:
    def test_basic(self):
        issue = {
            "number": 42,
            "title": "Fix login",
            "body": "Login is broken",
            "labels": [{"name": "status:backlog"}, {"name": "bug"}],
            "assignee": "jre",
            "html_url": "https://github.com/o/r/issues/42",
        }
        ticket = _issue_to_ticket(issue)
        assert ticket.id.source == "github"
        assert ticket.id.value == "42"
        assert ticket.title == "Fix login"
        assert ticket.status == TicketStatus.BACKLOG
        assert "bug" in ticket.label_names

    def test_ready_status(self):
        issue = {
            "number": 1,
            "title": "Ready ticket",
            "labels": [{"name": "status:ready"}],
        }
        ticket = _issue_to_ticket(issue)
        assert ticket.status == TicketStatus.READY

    def test_in_progress_status(self):
        issue = {
            "number": 2,
            "title": "WIP",
            "labels": [{"name": "status:in-progress"}],
        }
        ticket = _issue_to_ticket(issue)
        assert ticket.status == TicketStatus.IN_PROGRESS

    def test_no_labels(self):
        issue = {"number": 3, "title": "Plain"}
        ticket = _issue_to_ticket(issue)
        assert ticket.status == TicketStatus.BACKLOG
        assert ticket.labels == ()

    def test_string_labels(self):
        issue = {
            "number": 4,
            "title": "String labels",
            "labels": ["status:review", "bug"],
        }
        ticket = _issue_to_ticket(issue)
        assert ticket.status == TicketStatus.REVIEW

    def test_missing_body(self):
        issue = {"number": 5, "title": "No body", "body": None}
        ticket = _issue_to_ticket(issue)
        assert ticket.body == ""

    def test_priority_extraction(self):
        issue = {
            "number": 6,
            "title": "Urgent",
            "labels": [{"name": "priority:high"}, {"name": "status:backlog"}],
        }
        ticket = _issue_to_ticket(issue)
        from theswarm.domain.tickets.value_objects import TicketPriority
        assert ticket.priority == TicketPriority.HIGH


# ── Integration: GitHubTicketSource ──────────────────────────────


class FakeVCS:
    """Fake VCSPort for testing."""

    def __init__(self, issues: list[dict] | None = None) -> None:
        self._issues = issues or []
        self.updated: list[tuple[int, list[str] | None]] = []
        self.created: list[dict] = []

    async def get_issues(
        self, labels: list[str] | None = None, state: str = "open",
    ) -> list[dict]:
        result = []
        for issue in self._issues:
            if state != "all":
                issue_state = issue.get("state", "open")
                if issue_state != state:
                    continue
            if labels:
                issue_labels = [
                    lb.get("name", "") if isinstance(lb, dict) else str(lb)
                    for lb in issue.get("labels", [])
                ]
                if not any(lb in issue_labels for lb in labels):
                    continue
            result.append(issue)
        return result

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None,
    ) -> dict:
        issue = {
            "number": len(self._issues) + 100,
            "title": title,
            "body": body,
            "labels": [{"name": lb} for lb in (labels or [])],
        }
        self._issues.append(issue)
        self.created.append(issue)
        return issue

    async def update_issue(
        self, number: int, labels: list[str] | None = None, state: str | None = None,
    ) -> None:
        self.updated.append((number, labels))


class TestGitHubTicketSource:
    def _make_source(self, issues: list[dict] | None = None) -> tuple[GitHubTicketSource, FakeVCS]:
        vcs = FakeVCS(issues)
        return GitHubTicketSource(vcs), vcs

    async def test_get_backlog(self):
        source, _ = self._make_source([
            {"number": 1, "title": "A", "labels": [{"name": "status:backlog"}]},
            {"number": 2, "title": "B", "labels": [{"name": "status:ready"}]},
        ])
        tickets = await source.get_backlog()
        assert len(tickets) == 1
        assert tickets[0].title == "A"

    async def test_get_ready(self):
        source, _ = self._make_source([
            {"number": 1, "title": "A", "labels": [{"name": "status:ready"}]},
        ])
        tickets = await source.get_ready()
        assert len(tickets) == 1

    async def test_get_in_progress(self):
        source, _ = self._make_source([
            {"number": 1, "title": "A", "labels": [{"name": "status:in-progress"}]},
        ])
        tickets = await source.get_in_progress()
        assert len(tickets) == 1

    async def test_transition(self):
        source, vcs = self._make_source([
            {"number": 5, "title": "X", "labels": [{"name": "status:backlog"}, {"name": "bug"}]},
        ])
        await source.transition("5", TicketStatus.READY)
        assert len(vcs.updated) == 1
        assert vcs.updated[0][0] == 5
        assert "status:ready" in vcs.updated[0][1]
        assert "bug" in vcs.updated[0][1]
        assert "status:backlog" not in vcs.updated[0][1]

    async def test_transition_not_found(self):
        source, vcs = self._make_source([])
        await source.transition("999", TicketStatus.READY)
        assert len(vcs.updated) == 0

    async def test_create(self):
        source, vcs = self._make_source([])
        ticket = await source.create("New ticket", "Description", ["bug"])
        assert ticket.title == "New ticket"
        assert len(vcs.created) == 1

    async def test_empty_backlog(self):
        source, _ = self._make_source([])
        tickets = await source.get_backlog()
        assert tickets == []
