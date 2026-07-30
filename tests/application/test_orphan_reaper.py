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

    async def reap_orphans(self, *, max_age_seconds: int) -> int:
        self.calls.append(max_age_seconds)
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
