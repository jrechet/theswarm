"""The cycles waiting their turn survive a restart (2026-10-11).

The owner played six features at 19:02: two ran, four waited behind them on
their repositories — in the tracker's memory only, so any deploy would have
dropped them without a word. A waiting cycle is written down (v040), taken
off when it starts or when a person cancels it, kept when a shutdown cancels
it, and started again at boot under its own id, in its order.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from theswarm import api as api_mod
from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle
from theswarm.infrastructure.persistence.cycle_queue_repo import SQLiteCycleQueue
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def queue(tmp_path):
    conn = await init_db(str(tmp_path / "q.db"))
    store = SQLiteCycleQueue(conn)
    api_mod.set_cycle_queue(store)
    yield store
    api_mod.set_cycle_queue(None)
    await conn.close()


class _Harness:
    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}

    async def body(self, cycle_id: str, repo: str, *_a, **_kw) -> None:
        await self.gates[cycle_id].wait()

    def cycle(self, repo: str, issue: int) -> str:
        record = get_cycle_tracker().create(CycleRequest(repo=repo, issue_number=issue,
                                                         description=f"Play on issue #{issue}"))
        self.gates[record.id] = asyncio.Event()
        return record.id


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    await asyncio.sleep(0.02)


async def test_a_waiting_cycle_is_written_down_and_taken_off_when_it_starts(queue):
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, b = h.cycle("o/app", 265), h.cycle("o/app", 218)
        ta = asyncio.create_task(run_api_cycle(a, "o/app", "", "", [], issue_number=265))
        await _settle()
        tb = asyncio.create_task(run_api_cycle(b, "o/app", "", "", [], issue_number=218))
        await _settle()

        rows = await queue.list_all()
        assert [(r["id"], r["issue_number"], r["description"]) for r in rows] == [(b, 218, "Play on issue #218")]

        h.gates[a].set()
        await _settle()
        assert await queue.list_all() == []  # #218 started
        h.gates[b].set()
        await asyncio.gather(ta, tb)


async def test_a_person_cancelling_a_waiting_cycle_takes_it_off(queue):
    h = _Harness()
    tracker = get_cycle_tracker()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, b = h.cycle("o/app", 265), h.cycle("o/app", 217)
        ta = asyncio.create_task(run_api_cycle(a, "o/app", "", "", [], issue_number=265))
        await _settle()
        tb = asyncio.create_task(run_api_cycle(b, "o/app", "", "", [], issue_number=217))
        tracker.set_task(b, tb)
        await _settle()
        tracker.cancel(b)
        await _settle()
        assert await queue.list_all() == []
        h.gates[a].set()
        await ta


async def test_a_shutdown_leaves_a_waiting_cycle_written_down(queue):
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, b = h.cycle("o/app", 265), h.cycle("o/app", 215)
        ta = asyncio.create_task(run_api_cycle(a, "o/app", "", "", [], issue_number=265))
        await _settle()
        tb = asyncio.create_task(run_api_cycle(b, "o/app", "", "", [], issue_number=215))
        await _settle()
        tb.cancel()  # what loop teardown does on SIGTERM
        with pytest.raises(asyncio.CancelledError):
            await tb
        assert [r["id"] for r in await queue.list_all()] == [b]
        h.gates[a].set()
        await ta


async def test_a_cycle_that_starts_at_once_is_never_written(queue):
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a = h.cycle("o/other", 1)
        ta = asyncio.create_task(run_api_cycle(a, "o/other", "", "", [], issue_number=1))
        await _settle()
        assert await queue.list_all() == []
        h.gates[a].set()
        await ta


async def test_a_cycle_started_again_that_runs_at_once_leaves_the_queue(queue):
    """The restart demo's #17 started at once after the boot and stayed in the
    table: the next boot would have started it again."""
    await queue.add("q17q17q17q17", "o/free", 17, "Play on issue #17", "2026-10-11T19:16:03+00:00")
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        record = get_cycle_tracker().create(CycleRequest(repo="o/free", issue_number=17), cycle_id="q17q17q17q17")
        h.gates[record.id] = asyncio.Event()
        task = asyncio.create_task(run_api_cycle(record.id, "o/free", "", "", [], issue_number=17))
        await _settle()
        assert await queue.list_all() == []
        h.gates[record.id].set()
        await task


async def test_the_boot_starts_them_again_under_their_ids_in_their_order(queue, monkeypatch):
    from theswarm.presentation.web import server

    await queue.add("q218q218q218", "o/app", 218, "Play on issue #218", "2026-10-11T19:02:52+00:00")
    await queue.add("q217q217q217", "o/app", 217, "Play on issue #217", "2026-10-11T19:02:54+00:00")
    started: list[tuple] = []

    async def start(state, owner, name, issue, description, *, cycle_id=None, queued_at=None):
        started.append((f"{owner}/{name}", issue, cycle_id, queued_at))

    monkeypatch.setattr("theswarm.presentation.web.routes.common.start_targeted_cycle", start)
    count = await server._relaunch_queue(SimpleNamespace(state=SimpleNamespace()), queue)

    assert count == 2
    assert started == [("o/app", 218, "q218q218q218", "2026-10-11T19:02:52+00:00"),
                       ("o/app", 217, "q217q217q217", "2026-10-11T19:02:54+00:00")]


async def test_a_relaunched_cycle_keeps_its_id_and_its_queue_time():
    record = get_cycle_tracker().create(CycleRequest(repo="o/app", issue_number=218),
                                        cycle_id="q218q218q218", created_at="2026-10-11T19:02:52+00:00")
    assert record.id == "q218q218q218" and record.created_at == "2026-10-11T19:02:52+00:00"
