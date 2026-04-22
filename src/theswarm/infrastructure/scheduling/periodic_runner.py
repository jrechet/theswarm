"""Background periodic runner for PO watch jobs.

The existing ``CronScheduler`` is dedicated to triggering development cycles
via ``RunCycleHandler``. Watch jobs (competitor scan, ecosystem scan, digest
generation) need their own lightweight runner because they fire arbitrary
async callables, not cycle commands.

Each registered job fires on a fixed interval. The runner is optional — if
the process is torn down, jobs stop cleanly via ``stop()``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

JobCallable = Callable[[], Awaitable[None]]


@dataclass
class PeriodicJob:
    name: str
    interval_seconds: float
    callable: JobCallable
    last_run: datetime | None = None
    last_error: str = ""
    run_count: int = 0


class PeriodicRunner:
    """Run registered async jobs on fixed intervals.

    Jobs do not overlap with themselves (next tick skips if still running).
    """

    def __init__(self, *, tick_seconds: float = 30.0) -> None:
        self._jobs: list[PeriodicJob] = []
        self._tick = tick_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._in_flight: set[str] = set()

    def register(self, job: PeriodicJob) -> None:
        existing = {j.name for j in self._jobs}
        if job.name in existing:
            raise ValueError(f"job {job.name!r} already registered")
        self._jobs.append(job)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def jobs(self) -> list[PeriodicJob]:
        return list(self._jobs)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("PeriodicRunner started with %d jobs", len(self._jobs))

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("PeriodicRunner stopped")

    async def tick_once(self) -> None:
        """Run all jobs that are due right now (useful for tests)."""
        await self._tick_once()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick_once()
            except Exception:  # pragma: no cover - defensive
                log.exception("PeriodicRunner tick failed")
            await asyncio.sleep(self._tick)

    async def _tick_once(self) -> None:
        now = datetime.now(timezone.utc)
        for job in self._jobs:
            if job.name in self._in_flight:
                continue
            if job.last_run is not None:
                elapsed = (now - job.last_run).total_seconds()
                if elapsed < job.interval_seconds:
                    continue
            asyncio.create_task(self._run_job(job))

    async def _run_job(self, job: PeriodicJob) -> None:
        self._in_flight.add(job.name)
        try:
            log.info("PeriodicRunner firing %s", job.name)
            await job.callable()
            job.run_count += 1
            job.last_error = ""
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("periodic job %s failed", job.name)
            job.last_error = str(exc)
        finally:
            job.last_run = datetime.now(timezone.utc)
            self._in_flight.discard(job.name)
