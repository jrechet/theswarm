"""Sprint G5 — cycle resume route and detail UI tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.checkpoint import PhaseCheckpoint
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCheckpointRepository,
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "resume.db"))
    yield conn
    await conn.close()


def _ck(cid: str, phase: str, ok: bool) -> PhaseCheckpoint:
    return PhaseCheckpoint(
        cycle_id=cid,
        phase=phase,
        state_json=json.dumps({"phase": phase}),
        ok=ok,
        completed_at=datetime.now(timezone.utc),
    )


async def _seed_failed_cycle(db, cid: str, resume_phase: str | None) -> Cycle:
    cycle_repo = SQLiteCycleRepository(db)
    cycle = Cycle(
        id=CycleId(cid),
        project_id="alpha",
        status=CycleStatus.FAILED,
        started_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
    )
    await cycle_repo.save(cycle)

    if resume_phase:
        ckpt_repo = SQLiteCheckpointRepository(db)
        # Walk PHASE_ORDER: mark everything before resume_phase as ok
        from theswarm.domain.cycles.checkpoint import PHASE_ORDER
        idx = PHASE_ORDER.index(resume_phase)
        for phase in PHASE_ORDER[:idx]:
            await ckpt_repo.save(_ck(cid, phase, True))
        # The failing phase itself
        await ckpt_repo.save(_ck(cid, resume_phase, False))
    return cycle


async def test_checkpoints_endpoint_returns_list_and_resumable(db):
    bus = EventBus()
    cycle = await _seed_failed_cycle(db, "cyc-g5-a", "dev_loop")

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    ckpt_repo = SQLiteCheckpointRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        checkpoint_repo=ckpt_repo,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cycle.id}/checkpoints")

    assert r.status_code == 200
    body = r.json()
    assert body["cycle_id"] == str(cycle.id)
    assert body["resumable_from"] == "dev_loop"
    phases = [c["phase"] for c in body["checkpoints"]]
    assert phases == ["po_morning", "techlead_breakdown", "dev_loop"]


async def test_detail_shows_resume_button_when_failed_and_resumable(db):
    bus = EventBus()
    cycle = await _seed_failed_cycle(db, "cyc-g5-b", "qa")

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    ckpt_repo = SQLiteCheckpointRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        checkpoint_repo=ckpt_repo,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cycle.id}")

    assert r.status_code == 200
    assert "↻ Resume from qa" in r.text
    assert f"/cycles/{cycle.id}/resume" in r.text


async def test_detail_hides_resume_when_no_checkpoints(db):
    bus = EventBus()
    cycle = await _seed_failed_cycle(db, "cyc-g5-c", None)

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    ckpt_repo = SQLiteCheckpointRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        checkpoint_repo=ckpt_repo,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cycle.id}")

    assert r.status_code == 200
    assert "↻ Resume" not in r.text


async def test_detail_hides_resume_when_cycle_completed(db):
    bus = EventBus()
    cycle_repo = SQLiteCycleRepository(db)
    project_repo = SQLiteProjectRepository(db)
    ckpt_repo = SQLiteCheckpointRepository(db)

    cid = "cyc-g5-d"
    cycle = Cycle(
        id=CycleId(cid),
        project_id="alpha",
        status=CycleStatus.COMPLETED,
        started_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
    )
    await cycle_repo.save(cycle)
    # Even with checkpoints, completed cycles should not show Resume
    await ckpt_repo.save(_ck(cid, "po_morning", True))
    await ckpt_repo.save(_ck(cid, "techlead_breakdown", True))

    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        checkpoint_repo=ckpt_repo,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/cycles/{cid}")

    assert r.status_code == 200
    assert "↻ Resume" not in r.text


async def test_checkpoints_endpoint_graceful_when_repo_missing(db):
    bus = EventBus()
    await _seed_failed_cycle(db, "cyc-g5-e", None)

    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        # checkpoint_repo deliberately omitted
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/cycles/cyc-g5-e/checkpoints")

    assert r.status_code == 200
    body = r.json()
    assert body["checkpoints"] == []
    assert body["resumable_from"] is None
