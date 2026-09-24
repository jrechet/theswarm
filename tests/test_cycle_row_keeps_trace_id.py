"""A cycle's row keeps its trace id and its continuation across phases.

The first `PhaseChanged` saved the row with `trace_id = ''`: `Cycle.add_phase`
and the handler's own rebuild listed every field but `trace_id` and
`resumed_as`, and `SQLiteCycleRepository.save` is an INSERT OR REPLACE. The
theater's `trace ↗` link and `GET /api/cycles/{id}` read that column, so
every cycle that reached its first phase lost its trace. A test that sent
CycleStarted then CycleCompleted, and nothing between, never saw it.
"""

from __future__ import annotations

from theswarm.application.events.bus import EventBus
from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
from theswarm.domain.cycles.events import (
    CycleCancelled,
    CycleCompleted,
    CycleFailed,
    CycleStarted,
    PhaseChanged,
)
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus, PhaseStatus
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, init_db

TRACE = "a" * 32


async def _bus_over(repo: SQLiteCycleRepository) -> EventBus:
    bus = EventBus()
    handler = CyclePersistenceHandler(repo)
    for event_type in (CycleStarted, PhaseChanged, CycleCompleted, CycleFailed, CycleCancelled):
        bus.subscribe(event_type, handler.handle)
    return bus


async def _phase(bus: EventBus, cycle_id: CycleId, phase: str, agent: str) -> None:
    await bus.publish(PhaseChanged(cycle_id=cycle_id, project_id="o/r", phase=phase, agent=agent))


async def test_the_first_phase_keeps_the_trace_id(tmp_path):
    db = await init_db(str(tmp_path / "swarm.db"))
    try:
        repo = SQLiteCycleRepository(db)
        bus = await _bus_over(repo)
        cid = CycleId("c-trace")

        await bus.publish(CycleStarted(cycle_id=cid, project_id="o/r", trace_id=TRACE))
        await _phase(bus, cid, "po_morning", "po")

        row = await repo.get(cid)
        assert row is not None
        assert row.trace_id == TRACE
    finally:
        await db.close()


async def test_phases_then_a_cancel_keep_trace_id_and_resumed_as(tmp_path):
    db = await init_db(str(tmp_path / "swarm.db"))
    try:
        repo = SQLiteCycleRepository(db)
        bus = await _bus_over(repo)
        cid = CycleId("c-cancel")

        await bus.publish(CycleStarted(cycle_id=cid, project_id="o/r", trace_id=TRACE))
        await repo.mark_resumed(str(cid), "c-next")
        await _phase(bus, cid, "po_morning", "po")
        await _phase(bus, cid, "techlead_breakdown", "techlead")
        await bus.publish(CycleCancelled(cycle_id=cid, project_id="o/r", reason="asked"))

        row = await repo.get(cid)
        assert row is not None
        assert row.status == CycleStatus.CANCELLED
        assert row.trace_id == TRACE
        assert row.resumed_as == "c-next"
        # The phases themselves are still recorded as before.
        assert [p.phase for p in row.phases] == ["po_morning", "techlead_breakdown"]
        assert [p.status for p in row.phases] == [PhaseStatus.COMPLETED, PhaseStatus.FAILED]
        assert row.phases[-1].summary == "Cancelled: asked"
    finally:
        await db.close()


async def test_phases_then_a_failure_keep_the_trace_id(tmp_path):
    db = await init_db(str(tmp_path / "swarm.db"))
    try:
        repo = SQLiteCycleRepository(db)
        bus = await _bus_over(repo)
        cid = CycleId("c-fail")

        await bus.publish(CycleStarted(cycle_id=cid, project_id="o/r", trace_id=TRACE))
        await _phase(bus, cid, "po_morning", "po")
        await _phase(bus, cid, "dev_iter", "dev")
        await bus.publish(CycleFailed(cycle_id=cid, project_id="o/r", error="boom"))

        row = await repo.get(cid)
        assert row is not None
        assert row.status == CycleStatus.FAILED
        assert row.trace_id == TRACE
    finally:
        await db.close()
