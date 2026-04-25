"""SQLiteCycleRepository.reap_orphans — flips stale 'running' rows to 'failed'."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    init_db,
)


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "cycles.db"))
    yield SQLiteCycleRepository(conn)
    await conn.close()


def _running_cycle(cid: str, started_at: datetime) -> Cycle:
    return Cycle(
        id=CycleId(cid),
        project_id="proj",
        status=CycleStatus.RUNNING,
        triggered_by="test",
        started_at=started_at,
    )


async def test_reap_marks_old_running_cycles_failed(repo):
    long_ago = datetime.now(timezone.utc) - timedelta(hours=4)
    await repo.save(_running_cycle("stale", long_ago))

    n = await repo.reap_orphans(max_age_seconds=7200)
    assert n == 1

    saved = await repo.get(CycleId("stale"))
    assert saved is not None
    assert saved.status == CycleStatus.FAILED
    assert saved.completed_at is not None


async def test_reap_leaves_recent_running_cycles_alone(repo):
    just_now = datetime.now(timezone.utc) - timedelta(minutes=5)
    await repo.save(_running_cycle("fresh", just_now))

    n = await repo.reap_orphans(max_age_seconds=7200)
    assert n == 0

    saved = await repo.get(CycleId("fresh"))
    assert saved is not None
    assert saved.status == CycleStatus.RUNNING


async def test_reap_returns_zero_when_nothing_to_do(repo):
    n = await repo.reap_orphans()
    assert n == 0


async def test_reaped_cycle_has_orphan_summary_phase(repo):
    long_ago = datetime.now(timezone.utc) - timedelta(hours=4)
    await repo.save(_running_cycle("with-summary", long_ago))

    await repo.reap_orphans(max_age_seconds=7200)

    saved = await repo.get(CycleId("with-summary"))
    assert saved is not None
    assert saved.phases, "expected orphan phase to be appended"
    last = saved.phases[-1]
    assert last.phase == "system_orphan"
    assert "Orphaned by container restart" in last.summary
