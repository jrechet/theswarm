"""Stale-while-revalidate for what the pages read from GitHub.

A page that reads GitHub waits for GitHub: espace-client's board took 2.8 s
on prod (2026-10-11), 2.2 of them listing its issues, and the theater and a
feature page 1.5–2.4 s for the pinned issue — every time the cache had
expired, which was every visit after twenty seconds ("l'application est
globalement très lente", the owner). An answer is now kept per key: fresh
for `fresh` seconds, then still served — at once — for up to `keep`
seconds while one read in the background brings the next one. Only a key
never read, or read longer ago than `keep`, makes the page wait, and then
at most `timeout` seconds: the read goes on, every caller meanwhile waits
on that one read, and its answer is kept once it lands. A failed read is
never kept.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Generic, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class Swr(Generic[T]):
    def __init__(self, name: str, *, fresh: Callable[[], float], keep: Callable[[], float],
                 timeout: Callable[[], float], clock: Callable[[], float] = time.monotonic) -> None:
        self._name = name
        self._fresh = fresh
        self._keep = keep
        self._timeout = timeout
        self._clock = clock
        self._kept: dict[Hashable, tuple[float, T]] = {}
        self._inflight: dict[Hashable, asyncio.Task] = {}

    def clear(self) -> None:
        self._kept.clear()
        self._inflight.clear()

    def forget(self, key: Hashable) -> None:
        """The next read of `key` waits for GitHub (after a write the page shows)."""
        self._kept.pop(key, None)

    async def get(self, key: Hashable, load: Callable[[], Awaitable[T]], *, now: float | None = None) -> T:
        """The kept answer, fresh or stale; else the read's, within the timeout
        (`asyncio.TimeoutError` past it — the read goes on)."""
        moment = self._clock() if now is None else now
        fresh, keep = self._fresh(), self._keep()
        hit = self._kept.get(key) if fresh > 0 else None
        if hit is not None:
            age = moment - hit[0]
            if age < fresh:
                return hit[1]
            if age < max(keep, fresh):
                self._start(key, load, moment)
                return hit[1]
        task = self._start(key, load, moment)
        return await asyncio.wait_for(asyncio.shield(task), self._timeout())

    def _start(self, key: Hashable, load: Callable[[], Awaitable[T]], moment: float) -> asyncio.Task:
        task = self._inflight.get(key)
        if task is not None and not task.done():
            return task
        task = asyncio.ensure_future(self._read(key, load, moment))
        self._inflight[key] = task
        task.add_done_callback(lambda t, k=key: self._inflight.pop(k, None) if self._inflight.get(k) is t else None)
        task.add_done_callback(self._noted)
        return task

    def _noted(self, task: asyncio.Task) -> None:
        """A refresh nobody waited for still says why it failed."""
        if not task.cancelled() and task.exception() is not None:
            log.warning("%s: a read failed (%s) — the last answer stays", self._name, task.exception())

    async def _read(self, key: Hashable, load: Callable[[], Awaitable[T]], moment: float) -> T:
        value = await load()  # a failure propagates to whoever waits, and is not kept
        if self._fresh() > 0:
            self._kept[key] = (moment, value)
        return value
