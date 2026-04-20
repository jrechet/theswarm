"""Sprint E M2 — end-of-cycle retrospective service."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.application.services.report_generator import ReportGenerator
from theswarm.application.services.retrospective import RetrospectiveService
from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import (
    Budget,
    CycleId,
    CycleStatus,
    PhaseStatus,
)
from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteMemoryStore,
    init_db,
)


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "retro.db"))
    yield conn
    await conn.close()


def _cycle(
    *,
    phases: tuple[PhaseExecution, ...],
    budgets: tuple[Budget, ...] = (),
    status: CycleStatus = CycleStatus.COMPLETED,
) -> Cycle:
    start = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
    return Cycle(
        id=CycleId("c-1"),
        project_id="alpha",
        status=status,
        started_at=start,
        completed_at=start,
        phases=phases,
        budgets=budgets,
        total_cost_usd=sum(p.cost_usd for p in phases),
    )


def _phase(
    agent: str,
    phase: str = "work",
    *,
    status: PhaseStatus = PhaseStatus.COMPLETED,
    tokens: int = 10_000,
    cost: float = 0.05,
    summary: str = "",
) -> PhaseExecution:
    start = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
    return PhaseExecution(
        phase=phase, agent=agent,
        started_at=start, completed_at=start,
        status=status, tokens_used=tokens,
        cost_usd=cost, summary=summary,
    )


async def test_service_collects_failure_warning(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    cycle = _cycle(phases=(
        _phase("dev", phase="implement", status=PhaseStatus.FAILED,
               summary="tests failed after edit"),
    ))
    result = await service.run(cycle)
    assert len(result.learnings) >= 1
    assert any("failed" in l.lower() for l in result.learnings)
    entries = await store.query(project_id="alpha")
    assert any(e.category == MemoryCategory.ERRORS for e in entries)


async def test_service_flags_budget_pressure(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    cycle = _cycle(
        phases=(_phase("dev", tokens=950_000),),
        budgets=(Budget(role="dev", limit=1_000_000, used=950_000),),
    )
    result = await service.run(cycle)
    assert any("tighten prompts" in l or "raise budget" in l for l in result.learnings)
    entries = await store.query(project_id="alpha")
    assert any(e.category == MemoryCategory.IMPROVEMENTS for e in entries)


async def test_service_flags_high_cost_phase(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    cycle = _cycle(phases=(_phase("techlead", cost=4.2),))
    result = await service.run(cycle)
    assert any("cheaper model" in l for l in result.learnings)


async def test_service_emits_convention_for_clean_phase(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    cycle = _cycle(phases=(_phase("po", tokens=5_000, cost=0.02),))
    result = await service.run(cycle)
    # A healthy completed phase produces at least one convention-style learning.
    assert len(result.learnings) == 1
    assert "completed cleanly" in result.learnings[0]


async def test_service_caps_at_three_per_agent(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    phases = tuple(
        _phase("dev", phase=f"iter-{i}", status=PhaseStatus.FAILED, summary="broke")
        for i in range(5)
    )
    cycle = _cycle(phases=phases)
    entries = service.collect(cycle)
    by_agent: dict[str, int] = {}
    for e in entries:
        by_agent[e.agent] = by_agent.get(e.agent, 0) + 1
    assert by_agent["dev"] == 3


async def test_service_emits_at_least_one_per_agent(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    cycle = _cycle(phases=(
        _phase("po", tokens=0, cost=0.0),  # no activity → default convention
        _phase("dev", tokens=1_000, cost=0.01),
    ))
    entries = service.collect(cycle)
    agents = {e.agent for e in entries}
    assert agents == {"po", "dev"}


async def test_service_persists_to_memory_store(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    cycle = _cycle(phases=(_phase("qa", tokens=2_000, cost=0.01),))
    await service.run(cycle)
    saved = await store.query(project_id="alpha", agent="qa")
    assert len(saved) == 1
    assert saved[0].scope == ProjectScope(project_id="alpha")
    assert saved[0].cycle_date == "2026-04-20"


async def test_service_result_feeds_report_generator(db):
    store = SQLiteMemoryStore(db)
    service = RetrospectiveService(store)
    cycle = _cycle(phases=(
        _phase("po", tokens=3_000, cost=0.01),
        _phase("dev", tokens=10_000, cost=0.05),
    ))
    result = await service.run(cycle)
    report = ReportGenerator().generate(cycle, agent_learnings=result.learnings)
    assert report.agent_learnings == result.learnings
    assert len(report.agent_learnings) >= 2


async def test_service_wired_into_web_app(db):
    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository,
        SQLiteProjectRepository,
    )
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    app = create_web_app(
        SQLiteProjectRepository(db), SQLiteCycleRepository(db),
        EventBus(), SSEHub(),
        memory_store=SQLiteMemoryStore(db),
    )
    retro = getattr(app.state, "retrospective_service", None)
    assert retro is not None
    assert isinstance(retro, RetrospectiveService)
