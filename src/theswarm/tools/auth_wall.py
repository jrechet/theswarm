"""Expired Claude credentials, remembered for a while, in this process.

2026-09-29 13:47 UTC: prod came back from a two-day outage with its mounted
~/.claude session dead ("Failed to authenticate: OAuth session expired and
could not be refreshed"). The harness's cycle died in 26 s, was scored a
failed run and a regression, and tried to alert. A person has to renew the
credentials; until then every call is spent against the same wall.

Like `quota_wall`, but with no clock to read: the wall holds `HOLD`, then
one call tries again — someone may have logged in again where ~/.claude is
mounted. Not persisted: a redeploy is how new credentials arrive.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

HOLD = timedelta(minutes=10)

_wall: dict[str, object] = {}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def raise_wall(message: str, now: datetime | None = None) -> datetime:
    """Remember the credentials were rejected; until when calls refuse."""
    until = _now(now) + HOLD
    _wall.update(until=until, reason=message)
    log.error("Claude credentials rejected — no call before %s: %s",
              until.isoformat(timespec="minutes"), message)
    return until


def wall_until(now: datetime | None = None) -> datetime | None:
    """When a call may try again, None when nothing stands in the way."""
    until = _wall.get("until")
    if isinstance(until, datetime) and until > _now(now):
        return until
    return None


def reason() -> str:
    return str(_wall.get("reason") or "")


def clear() -> None:
    _wall.clear()
