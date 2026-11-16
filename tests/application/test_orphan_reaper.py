"""Periodic orphan reap loop — concludes stale cycles between deploys.

Prod repro: reap_orphans only ran at server startup, so cycles hung on
2026-04-23 stayed 'running' until the next deploy on 2026-04-25 11:50.
"""

from __future__ import annotations

import asyncio

import pytest

from theswarm.application.services.orphan_reaper import run_orphan_reap_loop


class _FakeRepo:
    def __init__(self, fail_first: bool = False) -> None:
        self.calls: list[int] = []
        self._fail_first = fail_first

    async def reap_orphans(self, *, max_age_seconds: int, alive=frozenset()) -> int:
        self.calls.append(max_age_seconds)
        self.alive = alive
        if self._fail_first and len(self.calls) == 1:
            raise RuntimeError("db locked")
        return 1


async def _run_loop_briefly(repo: _FakeRepo, min_calls: int) -> None:
    task = asyncio.create_task(
        run_orphan_reap_loop(repo, max_age_seconds=12600, interval_seconds=0.01),
    )
    try:
        async with asyncio.timeout(2.0):
            while len(repo.calls) < min_calls:
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_loop_reaps_repeatedly_with_max_age():
    repo = _FakeRepo()
    await _run_loop_briefly(repo, min_calls=3)
    assert len(repo.calls) >= 3
    assert all(age == 12600 for age in repo.calls)


async def test_loop_survives_repo_errors():
    repo = _FakeRepo(fail_first=True)
    await _run_loop_briefly(repo, min_calls=2)
    assert len(repo.calls) >= 2  # kept looping after the first call raised


async def test_the_loop_tells_the_reaper_which_cycles_are_alive():
    """Age alone marked cycle 3ad75f7c8a28 failed while it waited for Claude's window."""
    repo = _FakeRepo()
    task = asyncio.create_task(
        run_orphan_reap_loop(repo, max_age_seconds=12600, interval_seconds=0.01, alive=lambda: frozenset({"abc123abc123"})),
    )
    try:
        async with asyncio.timeout(2.0):
            while not repo.calls:
                await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert repo.alive == frozenset({"abc123abc123"})


async def test_a_cycle_a_task_still_runs_is_alive_and_a_finished_one_is_not():
    from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker
    from theswarm.application.services.orphan_reaper import live_cycle_ids

    tracker = get_cycle_tracker()
    waiting = tracker.create(CycleRequest(repo="o/r", issue_number=1))
    done = tracker.create(CycleRequest(repo="o/r", issue_number=2))
    tracker.update_status(waiting.id, CycleStatus.RUNNING)
    tracker.update_status(done.id, CycleStatus.COMPLETED)

    async def forever():
        await asyncio.sleep(60)

    tasks = [asyncio.create_task(forever()), asyncio.create_task(forever())]
    tracker.set_task(waiting.id, tasks[0])
    tracker.set_task(done.id, tasks[1])
    try:
        alive = live_cycle_ids()
        assert waiting.id in alive and done.id not in alive
    finally:
        for task in tasks:
            task.cancel()
        for record in (waiting, done):
            tracker._cycles.pop(record.id, None)
            tracker._tasks.pop(record.id, None)
