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

# Grace period on top of the whole-cycle hard timeout before a 'running' row
# is treated as orphaned. Sits above the timeout so a cycle that is still
# legitimately executing is never reaped out from under its own task.
REAP_GRACE_SECONDS = 30 * 60


def reap_max_age_seconds() -> int:
    """Age at which a 'running' cycle row is considered orphaned.

    Single source of truth for the reaper loop and for the readiness banner,
    so the UI never promises a different cleanup window than the one that
    actually runs.
    """
    from theswarm.api import CYCLE_HARD_TIMEOUT_SECONDS

    return CYCLE_HARD_TIMEOUT_SECONDS + REAP_GRACE_SECONDS


class CycleReaperPort(Protocol):
    async def reap_orphans(self, *, max_age_seconds: int, alive: frozenset[str] = frozenset()) -> int: ...


def live_cycle_ids() -> frozenset[str]:
    """The cycles a task of this process still runs or holds in its queue.

    Age alone no longer tells an orphan from a live cycle: since A1 a cycle
    waits a closed Claude window out — hours, not counted against its hard
    timeout — and one past the age cutoff was reaped under its own task."""
    try:
        from theswarm.api import get_cycle_tracker

        tracker = get_cycle_tracker()
        return frozenset(
            cycle_id for cycle_id, task in tracker._tasks.items()
            if not task.done() and getattr(tracker.get(cycle_id), "status", None) is not None
            and tracker.get(cycle_id).status.value in ("running", "queued")
        )
    except Exception:  # noqa: BLE001 — no tracker to ask: the age rule alone, as before
        log.exception("The live cycles could not be read")
        return frozenset()


async def run_orphan_reap_loop(
    cycle_repo: CycleReaperPort,
    *,
    max_age_seconds: int,
    interval_seconds: float = DEFAULT_REAP_INTERVAL_SECONDS,
    alive=live_cycle_ids,
) -> None:
    """Reap stale 'running' cycles every ``interval_seconds``, forever.

    ``max_age_seconds`` must exceed the whole-cycle hard timeout so a
    legitimately running cycle is never reaped from under its task.
    Repo errors are logged and the loop continues.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            n = await cycle_repo.reap_orphans(max_age_seconds=max_age_seconds, alive=alive())
            if n:
                log.info("Periodic reap: %d stale running cycle(s) marked failed", n)
        except Exception:
            log.exception("Periodic orphan reap failed (loop continues)")
