"""The theater's activity feed shows what the agents said (seen in
docs/demos/v2-play-to-demo.webm).

The feed read `AgentThought`/`AgentStep` events — Sprint D's — and nothing
has emitted either since the pipeline moved to the ProgressBridge, which
writes `AgentActivity`. Cycle 28371c2016da stored 197 of those and the
feed said "Nothing yet — the swarm announces itself here." to the end.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from theswarm.api import get_cycle_tracker
from theswarm.application.events.bus import EventBus
from theswarm.application.queries.get_agent_thoughts import GetAgentThoughtsQuery
from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

T = datetime(2026, 9, 28, 15, 40, tzinfo=timezone.utc)


def _activity(agent: str, action: str, detail: str) -> dict:
    return {"agent": agent, "action": action, "detail": detail,
            "project_id": "jrechet/concert-tour-app", "cycle_id": {"value": "x"}}


async def _stored(tmp_path, cycle_id: str):
    conn = await init_db(str(tmp_path / "feed.db"))
    store = SQLiteCycleEventStore(conn)
    await store.append(cycle_id, "AgentActivity", T,
                       _activity("TechLead", "progress", "Breaking down stories into tasks…"))
    await store.append(cycle_id, "AgentActivity", T.replace(minute=45),
                       _activity("Dev", "pr_opened", "PR #393 opened: https://github.com/x/393"))
    await store.append(cycle_id, "AgentActivity", T.replace(minute=46),
                       _activity("TechLead", "review", "PR #393: APPROVE"))
    await store.append(cycle_id, "PhaseChanged", T, {"phase": "qa", "agent": "QA"})
    return conn, store


async def test_the_theater_query_reads_the_agents_activity(tmp_path):
    conn, store = await _stored(tmp_path, "28371c2016da")
    try:
        entries = await GetAgentThoughtsQuery(store).execute("28371c2016da", include_activity=True)
        sprint_d = await GetAgentThoughtsQuery(store).execute("28371c2016da")
    finally:
        await conn.close()

    assert [(e.kind, e.agent, e.text) for e in entries] == [
        ("progress", "TechLead", "Breaking down stories into tasks…"),
        ("pr_opened", "Dev", "PR #393 opened: https://github.com/x/393"),
        ("review", "TechLead", "PR #393: APPROVE"),
    ]
    assert sprint_d == []  # the V1 thoughts panel reads what it always read


async def test_the_theater_shows_the_feed(tmp_path):
    from theswarm.api import CycleRequest, CycleStatus

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=387))
    tracker.update_status(record.id, CycleStatus("completed"))
    conn, store = await _stored(tmp_path, record.id)
    try:
        app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
                             EventBus(), SSEHub(), base_path="", db=conn, cycle_event_store=store)
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issue = AsyncMock(return_value={"number": 387, "title": "Occupancy"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                html = (await client.get(f"/c/{record.id}")).text
    finally:
        tracker._cycles.pop(record.id, None)
        await conn.close()

    assert 'data-testid="feed"' in html
    assert "Nothing yet" not in html
    assert "PR #393: APPROVE" in html and "Breaking down stories into tasks" in html


# ── Fragments are not news ──────────────────────────────────────────────
# Every line Claude streams reaches the bridge: the rail of 28371c2016da
# ended on the PO saying "]" and QA saying "BASE_URL = 'http://127.0.0.1:8000'".


def test_a_sentence_is_telling_a_fragment_is_not():
    from theswarm.application.services.progress_bridge import is_telling

    for line in ("Breaking down stories into tasks…", "PR #393: APPROVE",
                 "Picked targeted task: #389 Implement GET /api/v1/concerts/{id}/occupancy",
                 "QA report: unit=325(pass) e2e=36(pass)", "Iteration 1/5", "Implementing #22"):
        assert is_telling(line), line
    for line in ("]", "}", "```", "", "   ", "BASE_URL = 'http://127.0.0.1:8000'",
                 '"status": "pass",', "import httpx", "def test_occupancy():", "return x"):
        assert not is_telling(line), line


def test_the_rail_keeps_the_last_telling_message():
    from theswarm.application.services import progress_bridge

    progress_bridge.record_live_progress("frag-1", "po", "Planned 4 stories for today")
    progress_bridge.record_live_progress("frag-1", "po", "]")

    (row,) = progress_bridge.get_live_progress("frag-1")
    assert row["message"] == "Planned 4 stories for today"


async def test_the_feed_leaves_fragments_out(tmp_path):
    from theswarm.api import CycleRequest, CycleStatus

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=387))
    tracker.update_status(record.id, CycleStatus("completed"))
    conn, store = await _stored(tmp_path, record.id)
    await store.append(record.id, "AgentActivity", T.replace(minute=50),
                       _activity("QA", "progress", "BASE_URL = 'http://127.0.0.1:8000'"))
    await store.append(record.id, "AgentActivity", T.replace(minute=51),
                       _activity("PO", "progress", "]"))
    try:
        app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
                             EventBus(), SSEHub(), base_path="", db=conn, cycle_event_store=store)
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issue = AsyncMock(return_value={"number": 387, "title": "Occupancy"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                html = (await client.get(f"/c/{record.id}")).text
    finally:
        tracker._cycles.pop(record.id, None)
        await conn.close()

    assert "BASE_URL" not in html
    assert html.count('class="feed-entry') == 3
