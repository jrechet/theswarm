"""Periodic reaper for cycles stuck in 'running' state.

The startup-only reap in server.py handles rows orphaned by a container
restart. This loop covers the other case seen in prod (April 2026,
concert-tour-app): the process keeps running but a cycle hangs in a spot
without its own timeout, so its row stays 'running' for days until the
next deploy. The loop concludes such rows within one interval once they
exceed the whole-cycle hard timeout.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

log = logging.getLogger(__name__)

DEFAULT_REAP_INTERVAL_SECONDS = 15 * 60


class CycleReaperPort(Protocol):
    async def reap_orphans(self, *, max_age_seconds: int) -> int: ...


async def run_orphan_reap_loop(
    cycle_repo: CycleReaperPort,
    *,
    max_age_seconds: int,
    interval_seconds: float = DEFAULT_REAP_INTERVAL_SECONDS,
) -> None:
    """Reap stale 'running' cycles every ``interval_seconds``, forever.

    ``max_age_seconds`` must exceed the whole-cycle hard timeout so a
    legitimately running cycle is never reaped from under its task.
    Repo errors are logged and the loop continues.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            n = await cycle_repo.reap_orphans(max_age_seconds=max_age_seconds)
            if n:
                log.info("Periodic reap: %d stale running cycle(s) marked failed", n)
        except Exception:
            log.exception("Periodic orphan reap failed (loop continues)")
