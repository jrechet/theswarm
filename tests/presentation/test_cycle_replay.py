"""Sprint D V2 — cycle replay route and event persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import (
    AgentActivity,
    CycleCompleted,
    CycleStarted,
    PhaseChanged,
)
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "replay.db"))
    yield conn
    await conn.close()


async def _seed_cycle(db, cid: str = "cyc-r1") -> Cycle:
    cycle_repo = SQLiteCycleRepository(db)
    cycle = Cycle(
        id=CycleId(cid),
        project_id="alpha",
        status=CycleStatus.COMPLETED,
        started_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
    )
    await cycle_repo.save(cycle)
    return cycle


async def test_cycle_event_store_persists_events_via_handler(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    cid = CycleId("cyc-persist")
    await bus.publish(
        CycleStarted(cycle_id=cid, project_id="alpha", triggered_by="web"),
    )
    await bus.publish(
        PhaseChanged(cycle_id=cid, project_id="alpha", phase="plan", agent="po"),
    )
    await bus.publish(
        AgentActivity(
            cycle_id=cid, project_id="alpha", agent="po",
            action="planning", detail="writing daily plan",
        ),
    )
    await bus.publish(
        CycleCompleted(cycle_id=cid, project_id="alpha", total_cost_usd=1.23),
    )

    records = await store.list_for_cycle("cyc-persist")
    types = [r.event_type for r in records]
    assert "CycleStarted" in types
    assert "PhaseChanged" in types
    assert "AgentActivity" in types
    assert "CycleCompleted" in types


async def test_replay_route_returns_scrubber_ui(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    cycle = await _seed_cycle(db)

    # Seed events directly at three distinct offsets
    t0 = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    await store.append(str(cycle.id), "CycleStarted", t0, {"cycle_id": str(cycle.id)})
    await store.append(
        str(cycle.id), "PhaseChanged", t0 + timedelta(seconds=3),
        {"phase": "plan", "agent": "po"},
    )
    await store.append(
        str(cycle.id), "CycleCompleted", t0 + timedelta(seconds=8),
        {"total_cost_usd": 0.5},
    )

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cycle.id}/replay")

    assert r.status_code == 200
    assert "Cycle Replay" in r.text
    assert "data-replay-range" in r.text
    assert "CycleStarted" in r.text
    assert "PhaseChanged" in r.text
    assert "CycleCompleted" in r.text


async def test_replay_json_endpoint_returns_ordered_frames(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    cycle = await _seed_cycle(db, "cyc-r2")

    t0 = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    await store.append(str(cycle.id), "CycleStarted", t0, {})
    await store.append(
        str(cycle.id), "AgentActivity", t0 + timedelta(milliseconds=500), {},
    )
    await store.append(
        str(cycle.id), "CycleCompleted", t0 + timedelta(seconds=2), {},
    )

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cycle.id}/replay.json")

    assert r.status_code == 200
    body = r.json()
    assert body["cycle_id"] == str(cycle.id)
    frames = body["frames"]
    assert len(frames) == 3
    assert frames[0]["offset_ms"] == 0
    assert frames[1]["offset_ms"] == 500
    assert frames[2]["offset_ms"] == 2000
    assert frames[0]["event_type"] == "CycleStarted"
    assert frames[-1]["event_type"] == "CycleCompleted"


async def test_replay_route_renders_empty_state_when_no_events(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    cycle = await _seed_cycle(db, "cyc-empty")

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cycle.id}/replay")

    assert r.status_code == 200
    assert "No replay data available" in r.text
    assert "data-replay-range" not in r.text


async def test_cycle_detail_links_to_replay(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    cycle = await _seed_cycle(db, "cyc-link")

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cycle.id}")

    assert r.status_code == 200
    assert f"/cycles/{cycle.id}/replay" in r.text
