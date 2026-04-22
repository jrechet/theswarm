"""Tests for PeriodicRunner."""

from __future__ import annotations

import asyncio

import pytest

from theswarm.infrastructure.scheduling.periodic_runner import (
    PeriodicJob,
    PeriodicRunner,
)


class TestPeriodicRunner:
    async def test_register_dedup(self):
        r = PeriodicRunner()
        r.register(PeriodicJob(name="a", interval_seconds=60, callable=_noop))
        with pytest.raises(ValueError):
            r.register(PeriodicJob(name="a", interval_seconds=60, callable=_noop))

    async def test_tick_once_runs_due_job(self):
        r = PeriodicRunner()
        calls = {"n": 0}

        async def inc() -> None:
            calls["n"] += 1

        r.register(PeriodicJob(name="tick", interval_seconds=0.01, callable=inc))
        await r.tick_once()
        # job spawned in background — give it a moment
        await asyncio.sleep(0.05)
        assert calls["n"] == 1

    async def test_job_does_not_overlap_itself(self):
        r = PeriodicRunner()
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow() -> None:
            started.set()
            await release.wait()

        r.register(PeriodicJob(name="slow", interval_seconds=0.0, callable=slow))
        await r.tick_once()
        await started.wait()
        # tick again while the first invocation is still in flight
        await r.tick_once()
        # The second tick must not have spawned a new invocation.
        # Release now.
        release.set()
        await asyncio.sleep(0.01)
        job = r.jobs[0]
        assert job.run_count == 1

    async def test_start_stop_lifecycle(self):
        r = PeriodicRunner(tick_seconds=0.01)
        r.register(PeriodicJob(name="lc", interval_seconds=1.0, callable=_noop))
        await r.start()
        assert r.running is True
        await r.stop()
        assert r.running is False


async def _noop() -> None:
    return None
