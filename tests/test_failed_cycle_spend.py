"""A failed cycle keeps what it spent.

The graph checkpoint carries the cycle's running total (`total_cost`), but
a cycle that failed, or that a restart ended and nobody continued, wrote
$0 on its row: csv-export on 2026-09-25 was scored at $0.00 after two
Claude-heavy phases and three merged PRs. A continuation inherits the
total through the checkpoint, so the interrupted row stays at $0 when it
is continued — the chain is counted once.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from theswarm import api as api_mod
from theswarm.application.services import cycle_resumer
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, init_db


class _Saver:
    def __init__(self, threads: dict[str, float]):
        self.threads = threads

    async def aget_tuple(self, config):
        thread_id = config["configurable"]["thread_id"]
        if thread_id not in self.threads:
            return None
        return SimpleNamespace(checkpoint={"channel_values": {"total_cost": self.threads[thread_id]}})


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "spend.db"))
    yield SQLiteCycleRepository(conn)
    await conn.close()


async def test_the_spend_is_read_off_the_graph_thread():
    saver = _Saver({"092596248fb9": 2.41})

    assert await cycle_resumer.spent_so_far(saver, "092596248fb9") == 2.41
    assert await cycle_resumer.spent_so_far(saver, "unknown") == 0.0
    assert await cycle_resumer.spent_so_far(None, "092596248fb9") == 0.0


async def test_an_unreadable_thread_costs_nothing():
    class Broken:
        async def aget_tuple(self, config):
            raise RuntimeError("database is locked")

    assert await cycle_resumer.spent_so_far(Broken(), "x") == 0.0


async def test_a_failed_event_writes_the_spend_on_the_row(repo):
    from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
    from theswarm.domain.cycles.events import CycleFailed

    await repo.save(Cycle(id=CycleId("aaaaaaaaaaaa"), project_id="p", status=CycleStatus.RUNNING,
                          triggered_by="web", started_at=datetime.now(timezone.utc)))

    await CyclePersistenceHandler(repo).handle(CycleFailed(
        cycle_id=CycleId("aaaaaaaaaaaa"), project_id="p", error="boom", total_cost_usd=1.87,
    ))

    assert (await repo.get(CycleId("aaaaaaaaaaaa"))).total_cost_usd == 1.87


async def test_a_cycle_that_fails_reports_what_it_spent(monkeypatch):
    async def boom(*_a, **kw):
        raise RuntimeError("phase qa timed out")

    published: list = []

    class Bus:
        async def publish(self, event):
            published.append(event)

    monkeypatch.setattr(api_mod, "_cycle_checkpointer", _Saver({"placeholder": 0.0}))
    tracker = api_mod.get_cycle_tracker()
    record = tracker.create(api_mod.CycleRequest(repo="owner/some-repo"))
    api_mod._cycle_checkpointer.threads[record.id] = 1.52

    with patch("theswarm.cycle.run_daily_cycle", side_effect=boom):
        await api_mod.run_api_cycle(
            cycle_id=record.id, repo="owner/some-repo", description="",
            callback_url="", allowed_repos=[], event_bus=Bus(),
        )

    from theswarm.domain.cycles.events import CycleFailed

    (failed,) = [e for e in published if isinstance(e, CycleFailed)]
    assert failed.total_cost_usd == 1.52
    assert tracker.get(record.id).result == {"cost_usd": 1.52}


async def test_a_continuation_that_fails_reports_the_chain_s_spend(monkeypatch):
    """Its thread is its origin's: the total includes the phases before the restart."""
    async def boom(*_a, **kw):
        raise RuntimeError("phase qa timed out")

    monkeypatch.setattr(api_mod, "_cycle_checkpointer", _Saver({"092596248fb9": 2.41}))
    tracker = api_mod.get_cycle_tracker()
    record = tracker.create(api_mod.CycleRequest(repo="owner/some-repo"))

    with patch("theswarm.cycle.run_daily_cycle", side_effect=boom):
        await api_mod.run_api_cycle(
            cycle_id=record.id, repo="owner/some-repo", description="",
            callback_url="", allowed_repos=[], resume_cycle_id="092596248fb9",
            resume_from="qa",
        )

    assert tracker.get(record.id).result == {"cost_usd": 2.41}


async def test_a_cycle_left_behind_at_boot_keeps_its_spend(repo):
    await repo.save(Cycle(id=CycleId("46ff31375dce"), project_id="jrechet/concert-tour-app",
                          status=CycleStatus.RUNNING, triggered_by="auto-resume:1",
                          started_at=datetime.now(timezone.utc)))
    items = [{"cycle_id": "46ff31375dce", "repo": "jrechet/concert-tour-app",
              "triggered_by": "auto-resume:1", "resume_from": None, "cost_usd": 2.41}]
    await repo.reap_orphans(max_age_seconds=0, reason=cycle_resumer.RESTART_REASON)

    await cycle_resumer.record_not_resumed(repo, items, cycle_resumer.plan_resumes(items))

    cycle = await repo.get(CycleId("46ff31375dce"))
    assert cycle.total_cost_usd == 2.41
    assert "already an automatic resume" in cycle.error


async def test_collecting_reads_the_spend_off_the_chain_s_thread(repo):
    await repo.save(Cycle(id=CycleId("092596248fb9"), project_id="p", status=CycleStatus.FAILED,
                          triggered_by="web", started_at=datetime.now(timezone.utc)))
    await repo.mark_resumed("092596248fb9", "46ff31375dce")
    await repo.save(Cycle(id=CycleId("46ff31375dce"), project_id="p", status=CycleStatus.RUNNING,
                          triggered_by="auto-resume:1", started_at=datetime.now(timezone.utc)))

    class NoPhases:
        async def last_ok(self, cycle_id):
            return None

    (item,) = await cycle_resumer.collect_interrupted(
        repo, NoPhases(), graph_checkpointer=_Saver({"092596248fb9": 2.41}),
    )

    assert item["cost_usd"] == 2.41


def test_the_harness_falls_back_to_the_row_s_cost():
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("cycle_e2e_spend", root / "scripts/cycle_e2e.py")
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)

    assert harness.cycle_cost({"total_cost_usd": 2.41, "result": {}}) == 2.41
    assert harness.cycle_cost({"total_cost_usd": 0.0, "result": {"cost_usd": 1.2}}) == 1.2
    assert harness.cycle_cost({}) == 0.0
