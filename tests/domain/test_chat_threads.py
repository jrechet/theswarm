"""Tests for chat thread + message domain entities (Phase B)."""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.domain.agents.entities import PORTFOLIO_PROJECT_ID
from theswarm.domain.chat.threads import AuthorKind, ChatMessage, ChatThread


class TestChatThread:
    def test_deterministic_id_stable_for_same_pair(self):
        a = ChatThread.deterministic_id("proj1", "Alice")
        b = ChatThread.deterministic_id("proj1", "Alice")
        assert a == b
        assert a.startswith("th_")

    def test_deterministic_id_differs_for_different_codenames(self):
        a = ChatThread.deterministic_id("proj1", "Alice")
        b = ChatThread.deterministic_id("proj1", "Bob")
        assert a != b

    def test_deterministic_id_differs_for_different_projects(self):
        a = ChatThread.deterministic_id("proj1", "Alice")
        b = ChatThread.deterministic_id("proj2", "Alice")
        assert a != b

    def test_team_thread_has_empty_codename(self):
        t = ChatThread(
            id=ChatThread.deterministic_id("demo", ""),
            project_id="demo",
        )
        assert t.is_team_thread is True
        assert t.display_title == "demo · team"

    def test_portfolio_thread(self):
        t = ChatThread(
            id=ChatThread.deterministic_id(PORTFOLIO_PROJECT_ID, "Kenji"),
            project_id=PORTFOLIO_PROJECT_ID,
            codename="Kenji",
            role="scout",
        )
        assert t.is_portfolio is True
        assert "Kenji" in t.display_title
        assert "SCOUT" in t.display_title

    def test_display_title_respects_custom_title(self):
        t = ChatThread(
            id="th_x",
            project_id="demo",
            codename="Mei",
            role="po",
            title="Mei's office hours",
        )
        assert t.display_title == "Mei's office hours"


class TestChatMessage:
    def test_new_id_uniqueness(self):
        ids = {ChatMessage.new_id() for _ in range(20)}
        assert len(ids) == 20

    def test_human_message(self):
        m = ChatMessage(
            id=ChatMessage.new_id(),
            thread_id="th_x",
            author_kind=AuthorKind.HUMAN,
            author_id="u1",
            author_display="Operator",
            body="@Alice ping",
        )
        assert m.author_kind is AuthorKind.HUMAN
        assert m.body == "@Alice ping"
        assert m.intent_action == ""

    def test_created_at_defaults_to_now(self):
        m = ChatMessage(
            id="msg_1",
            thread_id="th_1",
            author_kind=AuthorKind.AGENT,
            body="pong",
        )
        delta = datetime.now(timezone.utc) - m.created_at
        assert delta.total_seconds() < 5
