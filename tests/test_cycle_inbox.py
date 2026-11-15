"""Talking to a running cycle (A3.1).

The owner (2026-11-11): "pouvoir interagir avec un agent en cours : chatter
une correction". A message posted on the theater waits in the cycle's inbox,
shows in the feed, and is delivered once to the working agent: at its next
tool call (the PreToolUse hook's `additionalContext`) or at the head of the
next Claude call's prompt.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from claude_agent_sdk import ResultMessage, SystemMessage

from theswarm.application.services.cycle_inbox import (
    DELIVERY_HEADING,
    MAX_MESSAGE_CHARS,
    CycleInbox,
    InboxError,
    delivery_text,
)
from theswarm.infrastructure.persistence.cycle_inbox_repo import SQLiteCycleInbox
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI


class _Bus:
    def __init__(self):
        self.events: list = []

    async def publish(self, event):
        self.events.append(event)


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "inbox.db"))
    yield conn
    await conn.close()


# ── The inbox ──────────────────────────────────────────────────────────


async def test_a_message_waits_then_is_read_once(db):
    bus = _Bus()
    inbox = CycleInbox(SQLiteCycleInbox(db), bus)

    await inbox.post("c1", "  Use the existing\n VenueUpdate schema ", author="jrechet", project_id="o/r")
    await inbox.post("c1", "And keep the 409", author="jrechet", project_id="o/r")
    await inbox.post("c2", "another cycle's", project_id="o/r")

    assert await inbox.waiting("c1") == 2
    assert await inbox.take("c1", to="Dev", project_id="o/r") == [
        "Use the existing VenueUpdate schema", "And keep the 409"]
    assert await inbox.take("c1", to="TechLead") == [] and await inbox.waiting("c1") == 0
    assert await inbox.waiting("c2") == 1  # each cycle its own

    said = [(e.agent, e.action, e.detail) for e in bus.events]
    assert said[0] == ("owner", "message", "Use the existing VenueUpdate schema")
    assert said[-1] == ("owner", "message_read", "2 messages reached Dev")


async def test_an_empty_or_endless_message_is_refused(db):
    inbox = CycleInbox(SQLiteCycleInbox(db))
    with pytest.raises(InboxError):
        await inbox.post("c1", "   ")
    with pytest.raises(InboxError):
        await inbox.post("c1", "x" * (MAX_MESSAGE_CHARS + 1))
    assert await inbox.waiting("c1") == 0


async def test_an_inbox_that_cannot_be_read_never_fails_the_cycle():
    class _Broken:
        async def take(self, cycle_id, to):
            raise RuntimeError("database is locked")

        async def waiting(self, cycle_id):
            raise RuntimeError("database is locked")

    inbox = CycleInbox(_Broken())
    assert await inbox.take("c1", to="Dev") == [] and await inbox.waiting("c1") == 0


def test_the_agent_is_told_whose_word_it_is():
    text = delivery_text(["Use the existing schema"])
    assert text.startswith(DELIVERY_HEADING) and text.endswith("- Use the existing schema")
    assert delivery_text([]) == ""


# ── Delivery: the head of the next call, or the next tool call ────────


def _stream(prompts: list[str]):
    async def stream(prompt, options):
        prompts.append(prompt)
        yield SystemMessage(subtype="init", data={"apiKeySource": "none", "session_id": "s-1"})
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="s-1", total_cost_usd=0.0, usage={}, result="ok")

    return stream


async def test_what_was_said_heads_the_next_call_and_only_that_one(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    prompts: list[str] = []
    monkeypatch.setattr(claude_mod, "_sdk_query", _stream(prompts))
    waiting = [["Use the existing schema"], []]

    async def inbox():
        return waiting.pop(0)

    claude = ClaudeCLI(model="haiku", inbox=inbox)
    await claude.run("Implement the task")
    await claude.run("Review the PR")

    assert prompts[0].startswith(DELIVERY_HEADING) and prompts[0].endswith("Implement the task")
    assert "Use the existing schema" in prompts[0]
    assert prompts[1] == "Review the PR"


async def test_a_persona_s_claude_reads_the_same_inbox():
    async def inbox():
        return []

    base = ClaudeCLI(model="sonnet", inbox=inbox)
    assert base.with_settings("opus", "high").inbox is inbox
    assert base.for_task("review").inbox is inbox


async def test_an_allowed_tool_call_carries_what_was_said(tmp_path):
    waiting = [["Stop renaming the column"], []]

    async def inbox():
        return waiting.pop(0)

    hook = claude_mod._permission_hook("edit", str(tmp_path), inbox)
    call = {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "a.py")}}

    first = await hook(call, "t1", None)
    out = first["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and "permissionDecision" not in out
    assert "Stop renaming the column" in out["additionalContext"]
    assert await hook(call, "t2", None) == {}  # read once


async def test_a_refused_tool_call_is_still_refused_and_reads_nothing(tmp_path):
    read: list[int] = []

    async def inbox():
        read.append(1)
        return ["anything"]

    hook = claude_mod._permission_hook("edit", str(tmp_path), inbox)
    out = (await hook({"tool_name": "Read", "tool_input": {"file_path": "/etc/hostname"}}, "t1", None))[
        "hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and read == []


async def test_without_an_inbox_nothing_changes(tmp_path):
    hook = claude_mod._permission_hook("edit", str(tmp_path))
    assert await hook({"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "a.py")}}, "t", None) == {}


async def test_the_api_hands_each_cycle_its_own_reader(db):
    from theswarm import api

    inbox = CycleInbox(SQLiteCycleInbox(db))
    assert api._inbox_reader("c1", "o/r") is None  # tests, the CLI: no inbox
    api.set_cycle_inbox(inbox)
    try:
        await inbox.post("c1", "For c1")
        assert await api._inbox_reader("c2", "o/r")("Dev") == []
        assert await api._inbox_reader("c1", "o/r")("Dev") == ["For c1"]
    finally:
        api.set_cycle_inbox(None)


# ── The theater ────────────────────────────────────────────────────────


async def _theater(tmp_path, status):
    from theswarm.api import CycleRequest, get_cycle_tracker
    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=905))
    tracker.update_status(record.id, status)
    conn = await init_db(str(tmp_path / "t.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(),
                         base_path="/swarm", db=conn, cycle_event_store=SQLiteCycleEventStore(conn))
    return tracker, record, conn, app


async def test_the_owner_says_it_on_the_theater_and_the_feed_shows_it(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from theswarm.api import CycleStatus

    tracker, record, conn, app = await _theater(tmp_path, CycleStatus.RUNNING)
    try:
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issue = AsyncMock(return_value={"number": 905, "title": "Change a venue"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                page = (await client.get(f"/cycles/{record.id}")).text
                assert 'data-testid="say-field"' in page

                answer = await client.post(f"/cycles/{record.id}/messages",
                                           data={"message": "Use the existing VenueUpdate schema"})
                assert answer.status_code == 303 and answer.headers["location"].endswith("?said=1")
                assert await app.state.cycle_inbox.waiting(record.id) == 1

                stage = (await client.get(f"/cycles/{record.id}/stage")).text
                assert 'data-testid="feed-message"' in stage and "Use the existing VenueUpdate schema" in stage
                assert ">YOU<" in stage

                await app.state.cycle_inbox.take(record.id, to="Dev", project_id=record.repo)
                assert "The message reached Dev" in (await client.get(f"/cycles/{record.id}/stage")).text

                empty = await client.post(f"/cycles/{record.id}/messages", data={"message": "  "})
                assert empty.headers["location"].endswith("?said=empty")
    finally:
        tracker._cycles.pop(record.id, None)
        await conn.close()


async def test_a_cycle_that_is_over_takes_no_message(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from theswarm.api import CycleStatus

    tracker, record, conn, app = await _theater(tmp_path, CycleStatus.COMPLETED)
    try:
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issue = AsyncMock(return_value={"number": 905, "title": "Change a venue"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                assert 'data-testid="say-field"' not in (await client.get(f"/cycles/{record.id}")).text
                answer = await client.post(f"/cycles/{record.id}/messages", data={"message": "too late"})
                assert answer.headers["location"].endswith("?said=over")
                assert await app.state.cycle_inbox.waiting(record.id) == 0
    finally:
        tracker._cycles.pop(record.id, None)
        await conn.close()


async def test_a_member_cannot_talk_to_a_cycle():
    from theswarm.presentation.web.auth import MEMBER_ALLOWED

    assert not MEMBER_ALLOWED.match("/cycles/abc123def456/messages")
