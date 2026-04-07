"""Tests for theswarm.ticket_sources — protocol + GitHub adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.ticket_sources.protocol import Ticket, TicketSource, TicketStatus
from theswarm.ticket_sources.github_source import GitHubTicketSource, _issue_to_ticket


# ── Protocol compliance ─────────────────────────────────────────────


def test_github_source_is_ticket_source():
    """GitHubTicketSource satisfies the TicketSource protocol."""
    mock_gh = AsyncMock()
    source = GitHubTicketSource(mock_gh)
    assert isinstance(source, TicketSource)


def test_ticket_model():
    t = Ticket(id="42", title="Add login", source="github")
    assert t.id == "42"
    assert t.status == TicketStatus.BACKLOG
    assert t.labels == []


# ── _issue_to_ticket ────────────────────────────────────────────────


def test_issue_to_ticket_basic():
    issue = {
        "number": 42,
        "title": "Add OAuth",
        "body": "Implement Google OAuth",
        "labels": [{"name": "feature"}, {"name": "status:ready"}],
        "assignees": ["dev1"],
        "url": "https://github.com/o/r/issues/42",
    }
    ticket = _issue_to_ticket(issue)
    assert ticket.id == "42"
    assert ticket.title == "Add OAuth"
    assert ticket.status == TicketStatus.READY
    assert "feature" in ticket.labels
    assert ticket.source == "github"


def test_issue_to_ticket_no_status_label():
    issue = {
        "number": 1,
        "title": "Bug",
        "body": "",
        "labels": [{"name": "bug"}],
        "assignees": [],
        "url": "",
    }
    ticket = _issue_to_ticket(issue)
    assert ticket.status == TicketStatus.BACKLOG


def test_issue_to_ticket_string_labels():
    """Labels can be strings (from some API responses)."""
    issue = {
        "number": 1,
        "title": "Test",
        "body": "",
        "labels": ["status:in-progress"],
        "assignees": [],
        "url": "",
    }
    ticket = _issue_to_ticket(issue)
    assert ticket.status == TicketStatus.IN_PROGRESS


# ── GitHubTicketSource methods ──────────────────────────────────────


async def test_get_backlog():
    mock_gh = AsyncMock()
    mock_gh.get_issues.return_value = [
        {"number": 1, "title": "A", "body": "", "labels": [{"name": "status:backlog"}], "assignees": [], "url": ""},
        {"number": 2, "title": "B", "body": "", "labels": [{"name": "status:backlog"}], "assignees": [], "url": ""},
    ]
    source = GitHubTicketSource(mock_gh)
    tickets = await source.get_backlog()
    assert len(tickets) == 2
    assert all(t.status == TicketStatus.BACKLOG for t in tickets)
    mock_gh.get_issues.assert_called_once_with(labels=["status:backlog"])


async def test_get_ready():
    mock_gh = AsyncMock()
    mock_gh.get_issues.return_value = [
        {"number": 1, "title": "A", "body": "", "labels": [{"name": "status:ready"}], "assignees": [], "url": ""},
    ]
    source = GitHubTicketSource(mock_gh)
    tickets = await source.get_ready()
    assert len(tickets) == 1
    assert tickets[0].status == TicketStatus.READY


async def test_set_status():
    mock_gh = AsyncMock()
    source = GitHubTicketSource(mock_gh)

    await source.set_status("42", TicketStatus.IN_PROGRESS)

    # Should have removed old labels and added new one
    mock_gh.add_labels.assert_called_once_with(42, ["status:in-progress"])


async def test_create_ticket():
    mock_gh = AsyncMock()
    mock_gh.create_issue.return_value = {
        "number": 10,
        "title": "Implement endpoint",
        "body": "Details\n\nParent: #5",
        "labels": [{"name": "role:dev"}, {"name": "status:ready"}],
        "assignees": [],
        "url": "",
    }
    source = GitHubTicketSource(mock_gh)

    ticket = await source.create_ticket(
        title="Implement endpoint",
        body="Details",
        parent_id="5",
    )

    assert ticket.id == "10"
    assert ticket.source == "github"
    mock_gh.create_issue.assert_called_once()
    # Body should include parent reference
    call_body = mock_gh.create_issue.call_args[1]["body"]
    assert "Parent: #5" in call_body


async def test_add_comment():
    mock_gh = AsyncMock()
    source = GitHubTicketSource(mock_gh)

    await source.add_comment("42", "Looks good!")
    mock_gh.add_comment.assert_called_once_with(42, "Looks good!")


def test_source_name():
    mock_gh = AsyncMock()
    source = GitHubTicketSource(mock_gh)
    assert source.source_name == "github"


# ── TicketStatus enum ───────────────────────────────────────────────


def test_ticket_status_values():
    assert TicketStatus.BACKLOG.value == "backlog"
    assert TicketStatus.READY.value == "ready"
    assert TicketStatus.IN_PROGRESS.value == "in_progress"
    assert TicketStatus.REVIEW.value == "review"
    assert TicketStatus.DONE.value == "done"
