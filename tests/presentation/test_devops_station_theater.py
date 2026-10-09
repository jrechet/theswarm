"""The fifth station in the theater: DevOps, only in the cycles where it acted.

Its acts are `AgentActivity` events of agent `devops` in the cycle's event
store; the theater draws them as a station before the four — the preflight
(go, or no-go and the cycle refused) and the deploy watch (watching, landed,
late) — and in the feed under OPS. A cycle DevOps never acted in shows the
four agents, as before.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.api import get_cycle_tracker
from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository, init_db
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

T = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
GO = "Preflight: go — Claude fine · Disk (here) fine · Runners fine · CI slot not read"
WATCH = "Watching the deploy: 1 pull request merged to main — the new build replaces this server"
LANDED = "The deploy landed: this server runs f00d123, main's head — what the cycle merged is live"


def _act(agent, action, detail):
    return {"agent": agent, "action": action, "detail": detail, "project_id": "jrechet/theswarm", "metadata": {}}


@pytest.fixture()
async def rig(tmp_path):
    from theswarm.api import CycleRequest, CycleStatus

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/theswarm", issue_number=320))
    tracker.update_status(record.id, CycleStatus("completed"))
    conn = await init_db(str(tmp_path / "theater.db"))
    store = SQLiteCycleEventStore(conn)
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(),
                         base_path="", db=conn, cycle_event_store=store)
    yield app, store, record
    tracker._cycles.pop(record.id, None)
    await conn.close()


async def _theater(app, cycle_id) -> str:
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(return_value={"number": 320, "title": "Deploy watch"})
        klass.return_value.get_issues = AsyncMock(return_value=[])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            return (await client.get(f"/cycles/{cycle_id}")).text


def _station(html: str) -> str:
    m = re.search(r'<button type="button" data-role="devops" data-state="(\w+)"(.*?)</button>', html, re.S)
    return (m.group(1), m.group(2)) if m else (None, "")


class TestTheFifthStation:
    async def test_a_cycle_devops_never_acted_in_shows_the_four(self, rig):
        app, store, record = rig
        await store.append(record.id, "AgentActivity", T, _act("TechLead", "progress", "Breaking down stories into tasks…"))
        html = await _theater(app, record.id)
        assert "The four agents" in html and 'data-role="devops"' not in html

    async def test_the_preflight_and_the_watch_then_landed(self, rig):
        app, store, record = rig
        await store.append(record.id, "AgentActivity", T, _act("devops", "preflight", GO))
        await store.append(record.id, "AgentActivity", T.replace(hour=10), _act("devops", "deploy_watch", WATCH))
        html = await _theater(app, record.id)
        state, body = _station(html)
        assert "The five agents" in html and state == "active" and "watching the deploy" in body
        assert 'data-act="preflight"' in body and GO in body and 'data-act="deploy_watch"' in body and WATCH in body
        assert html.index('data-role="devops"') < html.index('data-role="po"')  # the preflight comes first
        assert re.search(r'data-agent="devops">.*?>OPS</span>.*?' + re.escape(GO), html, re.S)  # in the feed too
        await store.append(record.id, "AgentActivity", T.replace(hour=11), _act("devops", "deploy_landed", LANDED))
        state, body = _station(await _theater(app, record.id))
        assert state == "done" and "The deploy landed: this server runs f00d123" in body and WATCH not in body  # (the apostrophe is escaped)

    async def test_a_no_go_and_a_late_deploy_are_failures(self, rig):
        app, store, record = rig
        await store.append(record.id, "AgentActivity", T, _act("devops", "preflight_nogo",
                                                                "Preflight: no-go, the cycle is not started — Claude: the weekly window is shut"))
        state, body = _station(await _theater(app, record.id))
        assert state == "failed" and "the weekly window is shut" in body and 'data-act="preflight_nogo"' in body
        await store.append(record.id, "AgentActivity", T, _act("devops", "preflight", GO))
        await store.append(record.id, "AgentActivity", T.replace(hour=10), _act("devops", "deploy_late", "The deploy has not landed: the deploy of f00d123 failed (failure)"))
        state, body = _station(await _theater(app, record.id))
        assert state == "failed" and "has not landed" in body
