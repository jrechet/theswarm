"""Sprint D C5 — cost preview estimate + modal wiring."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.services.cost_estimator import CostEstimator
from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus, PhaseStatus
from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "cost.db"))
    yield conn
    await conn.close()


async def _mk_app(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    return create_web_app(project_repo, cycle_repo, EventBus(), SSEHub()), project_repo, cycle_repo


async def test_cost_estimator_falls_back_to_model_baseline_without_history(db):
    project = Project(
        id="alpha", repo=RepoUrl("o/alpha"),
        config=ProjectConfig(effort="medium"),
    )
    cycle_repo = SQLiteCycleRepository(db)
    est = CostEstimator(cycle_repo)
    e = await est.estimate(project)
    assert e.basis == "model_baseline"
    assert e.sample_size == 0
    assert e.tokens > 0
    assert e.cost_usd > 0
    assert set(e.models_by_phase.keys()) == {"po", "techlead", "dev", "qa"}


async def test_cost_estimator_uses_last_three_completed_cycles(db):
    project = Project(id="alpha", repo=RepoUrl("o/alpha"))
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    await project_repo.save(project)

    base = datetime(2026, 4, 20, tzinfo=timezone.utc)
    for i, (tokens, cost) in enumerate([(10_000, 0.2), (20_000, 0.4), (30_000, 0.6), (40_000, 0.8)]):
        phase = PhaseExecution(
            phase="done", agent="po",
            started_at=base.replace(minute=i),
            completed_at=base.replace(minute=i + 1),
            status=PhaseStatus.COMPLETED,
            tokens_used=tokens, cost_usd=cost,
        )
        await cycle_repo.save(Cycle(
            id=CycleId(f"c{i}"),
            project_id="alpha",
            status=CycleStatus.COMPLETED,
            started_at=base.replace(minute=i),
            completed_at=base.replace(minute=i + 1),
            phases=(phase,),
            total_cost_usd=cost,
        ))

    est = CostEstimator(cycle_repo)
    e = await est.estimate(project)
    assert e.basis == "history"
    assert e.sample_size == 3
    # Most recent three are (40k, 30k, 20k) averaged → 30k tokens, $0.60
    assert e.tokens == 30_000
    assert abs(e.cost_usd - 0.6) < 0.001


async def test_cost_estimator_skips_failed_cycles(db):
    project = Project(id="beta", repo=RepoUrl("o/beta"))
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    await project_repo.save(project)

    base = datetime(2026, 4, 20, tzinfo=timezone.utc)
    ok_phase = PhaseExecution(
        phase="done", agent="po",
        started_at=base, completed_at=base,
        status=PhaseStatus.COMPLETED,
        tokens_used=12_000, cost_usd=0.3,
    )
    fail_phase = PhaseExecution(
        phase="done", agent="po",
        started_at=base.replace(minute=5),
        status=PhaseStatus.FAILED,
        tokens_used=999_999, cost_usd=99.0,
    )
    await cycle_repo.save(Cycle(
        id=CycleId("c-ok"), project_id="beta",
        status=CycleStatus.COMPLETED,
        started_at=base, completed_at=base,
        phases=(ok_phase,),
        total_cost_usd=0.3,
    ))
    await cycle_repo.save(Cycle(
        id=CycleId("c-fail"), project_id="beta",
        status=CycleStatus.FAILED,
        started_at=base.replace(minute=5),
        phases=(fail_phase,),
        total_cost_usd=99.0,
    ))

    est = CostEstimator(cycle_repo)
    e = await est.estimate(project)
    assert e.basis == "history"
    assert e.sample_size == 1
    assert e.tokens == 12_000


async def test_cost_estimate_endpoint_returns_json(db):
    app, project_repo, _ = await _mk_app(db)
    await project_repo.save(Project(id="gamma", repo=RepoUrl("o/gamma")))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/gamma/cost-estimate")

    assert r.status_code == 200
    body = r.json()
    assert "tokens" in body
    assert "cost_usd" in body
    assert "basis" in body
    assert "models_by_phase" in body
    assert body["basis"] == "model_baseline"


async def test_cost_estimate_endpoint_404_when_project_missing(db):
    app, _, _ = await _mk_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/nope/cost-estimate")
    assert r.status_code == 404


async def test_project_detail_renders_cost_modal(db):
    app, project_repo, _ = await _mk_app(db)
    await project_repo.save(Project(id="delta", repo=RepoUrl("o/delta")))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/delta")

    assert r.status_code == 200
    assert 'id="cost-preview-modal"' in r.text
    assert 'id="run-cycle-btn"' in r.text
    assert 'data-estimate-url="/projects/delta/cost-estimate"' in r.text
    assert '/static/js/cost-preview.js' in r.text
    assert 'data-testid="cost-confirm"' in r.text
