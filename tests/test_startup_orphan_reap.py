"""At startup, every 'running' cycle is an orphan — whatever its age.

A cycle is 'running' only while its in-process task is alive; at startup no
task exists yet. The old 2h cutoff therefore spared precisely the cycles a
restart had just killed: prod cycle fc6609d29b32 still claimed to be running
an hour after the deploy that ended it, which is what "hung for hours" looked
like on the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    init_db,
)


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "t.db"))
    yield SQLiteCycleRepository(conn)
    await conn.close()


async def _running(repo, cycle_id: str, age_seconds: int) -> None:
    await repo.save(Cycle(
        id=CycleId(cycle_id), project_id="p", status=CycleStatus.RUNNING,
        triggered_by="test",
        started_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    ))


async def test_a_cycle_killed_seconds_ago_is_reaped(repo):
    """The exact case the old cutoff missed."""
    await _running(repo, "fc6609d29b32", age_seconds=30)

    assert await repo.reap_orphans(max_age_seconds=0) == 1

    cycle = await repo.get(CycleId("fc6609d29b32"))
    assert cycle.status == CycleStatus.FAILED


async def test_old_orphans_are_reaped_too(repo):
    await _running(repo, "aaaaaaaaaaaa", age_seconds=99_999)
    assert await repo.reap_orphans(max_age_seconds=0) == 1


async def test_finished_cycles_are_untouched(repo):
    await repo.save(Cycle(
        id=CycleId("bbbbbbbbbbbb"), project_id="p",
        status=CycleStatus.COMPLETED, triggered_by="test",
        started_at=datetime.now(timezone.utc),
    ))
    assert await repo.reap_orphans(max_age_seconds=0) == 0
    cycle = await repo.get(CycleId("bbbbbbbbbbbb"))
    assert cycle.status == CycleStatus.COMPLETED


async def test_the_periodic_loop_keeps_its_age_guard():
    """Only startup may reap indiscriminately: the loop runs while cycles live."""
    from theswarm.application.services.orphan_reaper import reap_max_age_seconds

    assert reap_max_age_seconds() > 0


def test_startup_passes_no_age_cutoff():
    source = Path("src/theswarm/presentation/web/server.py").read_text()
    assert "reap_orphans(max_age_seconds=0)" in source
