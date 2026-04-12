"""Tests for domain/tickets — 100% coverage target."""

from __future__ import annotations

import pytest

from theswarm.domain.tickets.entities import Ticket
from theswarm.domain.tickets.value_objects import (
    Label,
    TicketId,
    TicketPriority,
    TicketStatus,
)


class TestTicketId:
    def test_creation(self):
        tid = TicketId(source="github", value="42")
        assert str(tid) == "github:42"

    def test_jira(self):
        tid = TicketId(source="jira", value="PROJ-123")
        assert str(tid) == "jira:PROJ-123"


class TestLabel:
    def test_creation(self):
        l = Label(name="bug", color="#ff0000")
        assert str(l) == "bug"

    def test_default_color(self):
        l = Label(name="feature")
        assert l.color == ""


class TestTicketStatus:
    def test_all_values(self):
        assert TicketStatus.BACKLOG == "backlog"
        assert TicketStatus.READY == "ready"
        assert TicketStatus.IN_PROGRESS == "in_progress"
        assert TicketStatus.REVIEW == "review"
        assert TicketStatus.DONE == "done"
        assert TicketStatus.CANCELLED == "cancelled"


class TestTicketPriority:
    def test_all_values(self):
        assert TicketPriority.CRITICAL == "critical"
        assert TicketPriority.NONE == "none"


class TestTicket:
    def test_creation(self):
        t = Ticket(
            id=TicketId("github", "42"),
            title="Fix login bug",
            body="The login redirect loops",
        )
        assert t.title == "Fix login bug"
        assert t.status == TicketStatus.BACKLOG
        assert t.label_names == []

    def test_with_labels(self):
        t = Ticket(
            id=TicketId("github", "1"),
            title="Test",
            labels=(Label("bug"), Label("urgent")),
        )
        assert t.label_names == ["bug", "urgent"]

        t2 = t.with_labels((Label("feature"),))
        assert t2.label_names == ["feature"]
        assert t.label_names == ["bug", "urgent"]  # immutable

    def test_with_status(self):
        t = Ticket(id=TicketId("github", "1"), title="Test")
        t2 = t.with_status(TicketStatus.IN_PROGRESS)
        assert t2.status == TicketStatus.IN_PROGRESS
        assert t2.updated_at is not None
        assert t.status == TicketStatus.BACKLOG  # immutable

    def test_frozen(self):
        t = Ticket(id=TicketId("github", "1"), title="Test")
        with pytest.raises(AttributeError):
            t.title = "Changed"  # type: ignore[misc]
