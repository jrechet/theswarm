"""Sprint D V3 — AgentThought/AgentStep events and panel fragment."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.queries.get_agent_thoughts import GetAgentThoughtsQuery
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import AgentStep, AgentThought
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
    conn = await init_db(str(tmp_path / "thoughts.db"))
    yield conn
    await conn.close()


async def _seed_cycle(db, cid="cyc-t1"):
    cycle_repo = SQLiteCycleRepository(db)
    cycle = Cycle(
        id=CycleId(cid),
        project_id="alpha",
        status=CycleStatus.RUNNING,
        started_at=datetime(2026, 4, 20, 10, tzinfo=timezone.utc),
    )
    await cycle_repo.save(cycle)
    return cycle


async def test_thought_and_step_events_persisted_and_queried(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    cid = CycleId("cyc-t1")
    await bus.publish(
        AgentThought(
            cycle_id=cid, project_id="alpha", agent="dev",
            thought="Refactoring handler to use dataclass",
            phase="implement",
        ),
    )
    await bus.publish(
        AgentStep(
            cycle_id=cid, project_id="alpha", agent="dev",
            step="run_tests", detail="pytest tests/",
            phase="implement",
        ),
    )

    query = GetAgentThoughtsQuery(store)
    entries = await query.execute("cyc-t1")

    assert len(entries) == 2
    kinds = [e.kind for e in entries]
    assert "thought" in kinds and "step" in kinds
    thought = next(e for e in entries if e.kind == "thought")
    assert thought.agent == "dev"
    assert "Refactoring" in thought.text
    step = next(e for e in entries if e.kind == "step")
    assert step.text == "run_tests"
    assert step.detail == "pytest tests/"


async def test_thoughts_fragment_renders_entries(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    cycle = await _seed_cycle(db)

    # Seed two entries directly
    t = datetime(2026, 4, 20, 10, 5, tzinfo=timezone.utc)
    await store.append(
        str(cycle.id), "AgentThought", t,
        {"agent": "po", "thought": "Picking backlog issue #42", "phase": "plan"},
    )
    await store.append(
        str(cycle.id), "AgentStep", t,
        {"agent": "dev", "step": "open_pr", "detail": "PR #17", "phase": "implement"},
    )

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/fragments/cycle/{cycle.id}/thoughts")

    assert r.status_code == 200
    assert "Picking backlog issue" in r.text
    assert "open_pr" in r.text
    assert "PR #17" in r.text
    assert 'data-agent="po"' in r.text
    assert 'data-agent="dev"' in r.text


async def test_thoughts_fragment_shows_empty_state(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    cycle = await _seed_cycle(db, "cyc-t-empty")

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        cycle_event_store=store,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/fragments/cycle/{cycle.id}/thoughts")

    assert r.status_code == 200
    assert "No thoughts or steps captured yet" in r.text


async def test_cycle_detail_includes_thoughts_panel(db):
    bus = EventBus()
    store = SQLiteCycleEventStore(db)
    cycle = await _seed_cycle(db, "cyc-t-panel")

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
    assert "Thoughts & Steps" in r.text
    assert f"/fragments/cycle/{cycle.id}/thoughts" in r.text
