"""A closed subscription window, remembered until it reopens.

The prod container shares the Claude subscription with the owner's own
Claude Code. When the window ran out on 2026-09-27 ("You've hit your weekly
limit · resets Sep 29, 4am (UTC)"), the harness still created its story
issue, started a cycle, and the cycle died in 51 s on its first call — as
three cycles had at 12:40 two days before. Every call until the reset is a
call against a wall: this remembers the wall (per process; a restart
forgets it and the next cycle's first call raises it again), the wrapper
refuses to spend a call before it lifts, `/health` says when, and the
harness starts nothing.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# A window whose message names no reset time is held this long: long
# enough not to burn a cycle against it, short enough to try again soon.
DEFAULT_HOLD = timedelta(minutes=30)

_RESET_RE = re.compile(r"resets\s+(.+?)\s*\(UTC\)", re.IGNORECASE)
# "Sep 29, 4am", "Sep 29, 4:05pm", "1:20pm", "9:50am"
_FORMATS = ("%b %d, %I:%M%p", "%b %d, %I%p", "%I:%M%p", "%I%p")

_until: datetime | None = None
_reason: str = ""


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def reset_time_of(message: str, now: datetime | None = None) -> datetime | None:
    """The UTC time the message says the window reopens, None when it says none.

    A bare time is today's, or tomorrow's when it has passed; a date without
    a year is this year's, or next year's when it is more than a day gone.
    """
    match = _RESET_RE.search(message or "")
    if not match:
        return None
    text, now = match.group(1).strip(), _now(now)
    for fmt in _FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%b" in fmt:
            reset = parsed.replace(year=now.year, tzinfo=timezone.utc)
            if reset < now - timedelta(days=1):
                reset = reset.replace(year=now.year + 1)
        else:
            reset = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            if reset <= now:
                reset += timedelta(days=1)
        return reset
    return None


def raise_wall(message: str, now: datetime | None = None) -> datetime:
    """Remember that the window is closed; returns when it reopens.

    A later reset replaces an earlier one, never the reverse: a weekly
    wall outlasts the session wall raised beside it.
    """
    global _until, _reason
    now = _now(now)
    until = reset_time_of(message, now) or (now + DEFAULT_HOLD)
    if _until is None or until > _until:
        _until, _reason = until, message
        log.warning("Claude subscription window closed until %s — no call is spent before then: %s",
                    until.isoformat(timespec="minutes"), message)
    return _until


def wall_until(now: datetime | None = None) -> datetime | None:
    """When the window reopens, None when it is open (a passed wall clears)."""
    global _until, _reason
    if _until is not None and _now(now) >= _until:
        _until, _reason = None, ""
    return _until


def reason() -> str:
    """The message the wall was raised on, "" when there is none."""
    return _reason


def clear() -> None:
    global _until, _reason
    _until, _reason = None, ""
