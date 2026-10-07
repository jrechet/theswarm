"""The cycle event store persists events through its handler (from V1's replay tests, M6): it feeds the theater's feed."""

from __future__ import annotations

import pytest
from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.events import (
    AgentActivity,
    CycleCompleted,
    CycleStarted,
    PhaseChanged,
)
from theswarm.domain.cycles.value_objects import CycleId
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
