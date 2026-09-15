"""Cancelling a cycle must be final — the resumer brought one back.

I cancelled c865170a1c4d to clear the way for a deploy. The container came
back, read the cycles table, found the row still 'running' — cancel had only
ever touched the in-memory tracker — and relaunched it as 16f3b8af2cca on
top of the cycle I had just started. Two cycles, one workspace, no PR.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker, run_api_cycle
from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
from theswarm.application.services.cycle_resumer import collect_interrupted
from theswarm.domain.cycles.events import CycleCancelled, CycleStarted, PhaseChanged
from theswarm.domain.cycles.value_objects import CycleId, PhaseStatus
from theswarm.domain.cycles.value_objects import CycleStatus as StoredStatus
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "cycles.db"))
    yield conn
    await conn.close()


class _Bus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


class _Checkpoints:
    """A checkpoint store that would happily resume anything it is asked about."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def last_ok(self, cycle_id: str):
        self.asked.append(cycle_id)
        return type("CP", (), {"next_phase": "dev_loop"})()


async def _running_cycle(repo: SQLiteCycleRepository, cycle_id: str) -> CyclePersistenceHandler:
    handler = CyclePersistenceHandler(repo)
    await handler.handle(CycleStarted(
        cycle_id=CycleId(cycle_id), project_id="jrechet/theswarm", triggered_by="web",
    ))
    await handler.handle(PhaseChanged(
        cycle_id=CycleId(cycle_id), project_id="jrechet/theswarm",
        phase="dev_loop", agent="Dev",
    ))
    return handler


class TestTheRowIsUpdated:
    async def test_a_cancelled_cycle_is_no_longer_running_in_the_database(self, db):
        repo = SQLiteCycleRepository(db)
        handler = await _running_cycle(repo, "c865170a1c4d")
        assert [str(c.id) for c in await repo.list_running()] == ["c865170a1c4d"]

        await handler.handle(CycleCancelled(
            cycle_id=CycleId("c865170a1c4d"), project_id="jrechet/theswarm",
            reason="operator",
        ))

        assert await repo.list_running() == []

    async def test_the_stored_status_says_cancelled_not_failed(self, db):
        repo = SQLiteCycleRepository(db)
        handler = await _running_cycle(repo, "c865170a1c4d")

        await handler.handle(CycleCancelled(cycle_id=CycleId("c865170a1c4d")))

        stored = await repo.get(CycleId("c865170a1c4d"))
        assert stored.status == StoredStatus.CANCELLED
        assert stored.completed_at is not None

    async def test_the_running_phase_is_closed_with_the_reason(self, db):
        repo = SQLiteCycleRepository(db)
        handler = await _running_cycle(repo, "c865170a1c4d")

        await handler.handle(CycleCancelled(
            cycle_id=CycleId("c865170a1c4d"), reason="deploy incoming",
        ))

        last = (await repo.get(CycleId("c865170a1c4d"))).phases[-1]
        assert last.status != PhaseStatus.RUNNING
        assert "deploy incoming" in last.summary

    async def test_cancelling_an_unknown_cycle_does_not_raise(self, db):
        handler = CyclePersistenceHandler(SQLiteCycleRepository(db))

        await handler.handle(CycleCancelled(cycle_id=CycleId("never-started")))


class TestTheResumerCannotSeeIt:
    async def test_a_cancelled_cycle_is_not_interrupted(self, db):
        """The exact production sequence: running, cancelled, then a restart
        asks what to resume."""
        repo = SQLiteCycleRepository(db)
        handler = await _running_cycle(repo, "c865170a1c4d")
        await handler.handle(CycleCancelled(cycle_id=CycleId("c865170a1c4d")))
        checkpoints = _Checkpoints()

        interrupted = await collect_interrupted(repo, checkpoints)

        assert interrupted == []
        assert checkpoints.asked == []  # never even considered

    async def test_a_genuinely_interrupted_cycle_still_is(self, db):
        """The guard must not throw the resumer's real job away with it."""
        repo = SQLiteCycleRepository(db)
        await _running_cycle(repo, "interrupted-one")

        interrupted = await collect_interrupted(repo, _Checkpoints())

        assert [i["cycle_id"] for i in interrupted] == ["interrupted-one"]
        assert interrupted[0]["resume_from"] == "dev_loop"


class TestRunApiCyclePublishesIt:
    async def test_cancel_mid_run_publishes_cycle_cancelled(self):
        started = asyncio.Event()

        async def hang(*_a, **_kw):
            started.set()
            await asyncio.sleep(30)

        bus = _Bus()
        tracker = get_cycle_tracker()
        record = tracker.create(CycleRequest(repo="owner/some-repo"))

        with patch("theswarm.cycle.run_daily_cycle", side_effect=hang):
            task = asyncio.create_task(run_api_cycle(
                record.id, "owner/some-repo", "", "", [], event_bus=bus,
            ))
            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            await task  # the cancellation is absorbed and recorded

        cancelled = [e for e in bus.events if isinstance(e, CycleCancelled)]
        assert len(cancelled) == 1
        assert str(cancelled[0].cycle_id) == record.id
        assert cancelled[0].project_id == "owner/some-repo"
        assert tracker.get(record.id).status == CycleStatus.CANCELLED

    async def test_a_completed_cycle_publishes_no_cancellation(self):
        async def quick(*_a, **_kw):
            return {"date": "2026-09-15", "cost_usd": 0.0, "prs": [], "reviews": []}

        bus = _Bus()
        tracker = get_cycle_tracker()
        record = tracker.create(CycleRequest(repo="owner/some-repo"))

        with patch("theswarm.cycle.run_daily_cycle", side_effect=quick):
            await run_api_cycle(record.id, "owner/some-repo", "", "", [], event_bus=bus)

        assert not any(isinstance(e, CycleCancelled) for e in bus.events)
