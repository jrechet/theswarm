"""Sprint G1 — SQLiteCheckpointRepository tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from theswarm.domain.cycles.checkpoint import PHASE_ORDER, PhaseCheckpoint
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCheckpointRepository,
    init_db,
)


@pytest.fixture
async def repo(tmp_path):
    db = await init_db(str(tmp_path / "ckpt.db"))
    yield SQLiteCheckpointRepository(db)
    await db.close()


def _mk(cycle_id: str, phase: str, ok: bool, ts: datetime) -> PhaseCheckpoint:
    return PhaseCheckpoint(
        cycle_id=cycle_id,
        phase=phase,
        state_json=json.dumps({"phase": phase, "ok": ok}),
        ok=ok,
        completed_at=ts,
    )


async def test_save_and_list_preserves_order(repo):
    cid = "c1"
    now = datetime.now(timezone.utc)
    await repo.save(_mk(cid, "po_morning", True, now.replace(microsecond=1)))
    await repo.save(_mk(cid, "techlead_breakdown", True, now.replace(microsecond=2)))
    await repo.save(_mk(cid, "dev_loop", True, now.replace(microsecond=3)))

    items = await repo.list_for_cycle(cid)

    assert [c.phase for c in items] == [
        "po_morning", "techlead_breakdown", "dev_loop",
    ]
    assert all(c.ok for c in items)


async def test_save_is_idempotent_per_phase(repo):
    cid = "c1"
    now = datetime.now(timezone.utc)
    first = _mk(cid, "po_morning", True, now)
    second = _mk(cid, "po_morning", False, now.replace(microsecond=5))

    await repo.save(first)
    await repo.save(second)

    items = await repo.list_for_cycle(cid)
    assert len(items) == 1
    assert items[0].ok is False


async def test_last_ok_returns_latest_successful(repo):
    cid = "c1"
    now = datetime.now(timezone.utc)
    await repo.save(_mk(cid, "po_morning", True, now.replace(microsecond=1)))
    await repo.save(_mk(cid, "techlead_breakdown", True, now.replace(microsecond=2)))
    await repo.save(_mk(cid, "dev_loop", False, now.replace(microsecond=3)))

    last = await repo.last_ok(cid)
    assert last is not None
    assert last.phase == "techlead_breakdown"


async def test_last_ok_returns_none_when_all_failed(repo):
    cid = "c1"
    now = datetime.now(timezone.utc)
    await repo.save(_mk(cid, "po_morning", False, now))

    assert await repo.last_ok(cid) is None


async def test_cycles_are_isolated(repo):
    now = datetime.now(timezone.utc)
    await repo.save(_mk("c-a", "po_morning", True, now))
    await repo.save(_mk("c-b", "po_morning", True, now))

    a_items = await repo.list_for_cycle("c-a")
    b_items = await repo.list_for_cycle("c-b")

    assert len(a_items) == 1 and a_items[0].cycle_id == "c-a"
    assert len(b_items) == 1 and b_items[0].cycle_id == "c-b"


def test_next_phase_walks_phase_order():
    now = datetime.now(timezone.utc)
    ck = PhaseCheckpoint("c1", "po_morning", "{}", True, now)
    assert ck.next_phase == "techlead_breakdown"

    last = PhaseCheckpoint("c1", "po_evening", "{}", True, now)
    assert last.next_phase is None


def test_phase_order_invariant():
    assert PHASE_ORDER == (
        "po_morning",
        "techlead_breakdown",
        "dev_loop",
        "qa",
        "po_evening",
    )
