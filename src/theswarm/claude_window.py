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
import logging
import os
from datetime import datetime, timedelta, timezone

from theswarm.tools import quota_wall

log = logging.getLogger(__name__)

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
    """When the swarm may call Claude again, None while it may.

    The subscription's own wall, or the owner's share of the window spent
    (`over_share`) — whichever opens last.
    """
    now = utcnow()
    moments = [m for m in (quota_wall.wall_until(now), (over_share(now=now) or {}).get("resets_at")) if m]
    return max(moments) if moments else None


def worth_waiting(until: datetime | None, waited: timedelta, *, now: datetime | None = None) -> bool:
    """True when the window reopens soon enough, counting what this cycle already waited."""
    if until is None:
        return False
    moment = now or utcnow()
    return waited + max(timedelta(0), until - moment) <= max_wait()


def words(until: datetime) -> str:
    over = over_share()
    if over is not None and over["resets_at"] >= until:
        return f"{share_words(over)} — the cycle waits and goes on then"
    return (f"Claude's subscription window is closed until {until.astimezone(timezone.utc):%H:%M} UTC — "
            "the cycle waits and goes on then")


async def wait_out(until: datetime) -> timedelta:
    """Sleep until the wall has fallen; how long that took. A wall pushed
    further while sleeping (a weekly limit raised beside the session's) is
    the caller's to judge again."""
    started = utcnow()
    await sleep(max(0.0, (until - started).total_seconds()) + MARGIN.total_seconds())
    return utcnow() - started


# ── The swarm's share of the window (A1) ─────────────────────────────────
#
# Every Claude call says where the subscription's windows stand: a
# `RateLimitEvent`, whose `raw["unifiedWindows"]` carries each window's
# utilization and reset — "five_hour" at 0.05 and "seven_day" at 0.66 on the
# owner's account on 2026-11-14, while the event's own `utilization` field was
# None. The code threw it away. The owner's own Claude Code draws on the same
# window, and the swarm can leave him nothing (2026-11-11): past the share he
# sets (Settings → Cycles), the swarm calls Claude no more until the window
# resets — a cycle waits as it does for a closed window.

SHARE_SCOPE = "claude:share"  # its row among the cycle limits
DEFAULT_SHARE = 100  # all of it: no limit
MIN_SHARE = 10
WINDOW_NAMES = {
    "five_hour": "5-hour", "seven_day": "weekly", "seven_day_opus": "weekly Opus",
    "seven_day_sonnet": "weekly Sonnet", "overage": "overage",
}

_WINDOWS: dict[str, dict] = {}


def _moment(raw: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def note(info: object, *, now: datetime | None = None) -> None:
    """Keep what one `RateLimitInfo` says about the windows. Never raises."""
    if info is None:
        return
    try:
        moment = now or utcnow()
        seen: dict[str, tuple[float, datetime | None]] = {}
        unified = (getattr(info, "raw", None) or {}).get("unifiedWindows") or {}
        if isinstance(unified, dict):
            for name, window in unified.items():
                if isinstance(window, dict) and window.get("utilization") is not None:
                    seen[str(name)] = (float(window["utilization"]), _moment(window.get("resetsAt")))
        kind, used = getattr(info, "rate_limit_type", None), getattr(info, "utilization", None)
        if kind and used is not None and kind not in seen:
            seen[str(kind)] = (float(used), _moment(getattr(info, "resets_at", None)))
        for name, (used, resets_at) in seen.items():
            _WINDOWS[name] = {"utilization": max(0.0, min(1.0, used)), "resets_at": resets_at, "read_at": moment}
    except Exception:  # noqa: BLE001 — a reading lost, never a call
        log.debug("rate limit event not read: %r", info, exc_info=True)


def forget() -> None:
    _WINDOWS.clear()


def windows(*, now: datetime | None = None) -> list[dict]:
    """Every window last read and not reset since, the fullest first."""
    moment = now or utcnow()
    rows = [{"name": name, "label": WINDOW_NAMES.get(name, name), **w} for name, w in _WINDOWS.items()
            if w["resets_at"] is None or w["resets_at"] > moment]
    return sorted(rows, key=lambda w: -w["utilization"])


def _bounded(percent: int) -> int:
    return max(MIN_SHARE, min(DEFAULT_SHARE, int(percent)))


def env_share() -> int:
    """The instance's default: `SWARM_CLAUDE_WINDOW_SHARE`, else all of it."""
    try:
        chosen = int(os.environ.get("SWARM_CLAUDE_WINDOW_SHARE", "") or 0)
    except ValueError:
        chosen = 0
    return _bounded(chosen) if chosen else DEFAULT_SHARE


def share() -> int:
    """The percent of each window the swarm may use: the owner's (Settings →
    Cycles), else the instance's default; 100 is no limit."""
    from theswarm.cycle_gate import cycle_limits

    getter = getattr(cycle_limits(), "claude_share", None)
    chosen = getter() if callable(getter) else None
    return _bounded(chosen) if chosen else env_share()


def over_share(*, now: datetime | None = None) -> dict | None:
    """The window past the swarm's share that reopens last, None when none is."""
    limit = share()
    if limit >= DEFAULT_SHARE:
        return None
    over = [w for w in windows(now=now) if w["resets_at"] is not None and w["utilization"] * 100 >= limit]
    if not over:
        return None
    return {**max(over, key=lambda w: w["resets_at"]), "share": limit}


def share_words(over: dict) -> str:
    when = over["resets_at"].astimezone(timezone.utc)
    day = "" if when.date() == utcnow().date() else f"{when:%a %d} "
    return (f"Claude's {over['label']} window is at {over['utilization']:.0%}, the swarm's share is "
            f"{over['share']}% — no call before {day}{when:%H:%M} UTC")
