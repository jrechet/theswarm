"""A closed Claude subscription window is waited out, not died of (A1).

The window is the subscription's, shared by every cycle and by the owner's
own Claude Code. When it closes, the message names when it reopens
(`tools.quota_wall`); a cycle that met it used to end `failed` — three at
once on 2026-11-11, the third refused by its preflight before it started.
Now the cycle says it waits, sleeps until the wall falls (plus a margin),
and goes on from its last finished node on its own graph thread.

Not everything is worth waiting for: a weekly limit can be days away
(`SWARM_CLAUDE_WAIT_MAX_HOURS`, 6 by default, counts every wait of one
cycle), and dead credentials (`tools.auth_wall`) need a person.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from theswarm.tools import quota_wall

MARGIN = timedelta(seconds=90)  # the wall's time is a minute's; let the window open first
DEFAULT_MAX_HOURS = 6.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def max_wait() -> timedelta:
    try:
        hours = float(os.environ.get("SWARM_CLAUDE_WAIT_MAX_HOURS", DEFAULT_MAX_HOURS))
    except ValueError:
        hours = DEFAULT_MAX_HOURS
    return timedelta(hours=max(0.0, hours))


def closed_until() -> datetime | None:
    """When the subscription window reopens, None while it is open."""
    return quota_wall.wall_until(utcnow())


def worth_waiting(until: datetime | None, waited: timedelta, *, now: datetime | None = None) -> bool:
    """True when the window reopens soon enough, counting what this cycle already waited."""
    if until is None:
        return False
    moment = now or utcnow()
    return waited + max(timedelta(0), until - moment) <= max_wait()


def words(until: datetime) -> str:
    return (f"Claude's subscription window is closed until {until.astimezone(timezone.utc):%H:%M} UTC — "
            "the cycle waits and goes on then")


async def wait_out(until: datetime) -> timedelta:
    """Sleep until the wall has fallen; how long that took. A wall pushed
    further while sleeping (a weekly limit raised beside the session's) is
    the caller's to judge again."""
    started = utcnow()
    await sleep(max(0.0, (until - started).total_seconds()) + MARGIN.total_seconds())
    return utcnow() - started
