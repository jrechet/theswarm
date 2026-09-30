"""Can Claude answer right now? Asked, not read off a wall.

2026-09-30 07:22 UTC: the scheduled harness opened concert-tour-app#508
and started cycle 6e3d36ca7d1d, which died in 28 s on the credentials dead
since 2026-09-28. `/health` had said `claude: ok`: the auth wall is held
ten minutes in the process that ran into it (`auth_wall`), and nothing had
called Claude since the day before. Every scheduled run until a person
renews them would open a story, start a cycle and close the story again.

The probe asks. The walls first — nothing is spent against one that
stands — then one short call on the cycles' own path (`ClaudeCLI.run`,
the text profile): the token first, the session on disk in reserve, the
same markers raising the same walls. The answer carries the keys `/health`
uses (`claude`, `claude_auth`, `claude_quota_resets_at`). It is kept a
minute, and one probe runs at a time: a door that spends the subscription
is not one a loop can spend.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from theswarm.tools import auth_wall, quota_wall
from theswarm.tools.claude import ClaudeCLI, ClaudeFatalError

log = logging.getLogger(__name__)

PROBE_PROMPT = "Reply with exactly the single word: OK"
PROBE_MODEL = "haiku"
# The harness gives an API call 60 s; the token and the session on disk
# may each be tried once inside that.
PROBE_BUDGET_SECONDS = 45
KEEP = timedelta(minutes=1)

_state: dict[str, object] = {}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _lock() -> asyncio.Lock:
    lock = _state.get("lock")
    if not isinstance(lock, asyncio.Lock):
        lock = _state["lock"] = asyncio.Lock()
    return lock


def standing_wall() -> dict | None:
    """The answer while a wall stands, None when nothing is in the way."""
    until = quota_wall.wall_until()
    if until is not None:
        return {"claude": "quota_wall", "claude_quota_resets_at": until.isoformat(),
                "detail": quota_wall.reason()}
    if auth_wall.wall_until() is not None:
        return {"claude": "auth_expired", "claude_auth": auth_wall.reason() or "expired",
                "detail": auth_wall.reason()}
    return None


async def _ask(claude: ClaudeCLI) -> dict:
    """One short call; what it says of Claude."""
    try:
        result = await asyncio.wait_for(claude.run(PROBE_PROMPT, timeout=PROBE_BUDGET_SECONDS),
                                        PROBE_BUDGET_SECONDS)
    except ClaudeFatalError as exc:
        # The call raised the wall it ran into; one it did not name is a
        # failure like any other (the API fallback's own fatal errors).
        return standing_wall() or {"claude": "error", "detail": str(exc)[:300]}
    except asyncio.TimeoutError:
        return {"claude": "error", "detail": f"no answer in {PROBE_BUDGET_SECONDS} s"}
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never raises
        return {"claude": "error", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    return {"claude": "ok", "backend": getattr(result, "backend", ""),
            "cost_usd": round(float(getattr(result, "cost_usd", 0.0) or 0.0), 4)}


async def probe(claude: ClaudeCLI | None = None, *, now: datetime | None = None) -> dict:
    """``{"claude": "ok" | "auth_expired" | "quota_wall" | "error", …}``
    plus ``spent`` (whether a call was made) and ``checked_at``."""
    wall = standing_wall()
    if wall is not None:
        return {**wall, "spent": False, "checked_at": _now(now).isoformat()}
    async with _lock():
        kept = _state.get("answer")
        at = _state.get("at")
        if isinstance(kept, dict) and isinstance(at, datetime) and _now(now) - at < KEEP:
            return {**kept, "spent": False}
        answer = await _ask(claude or ClaudeCLI(model=PROBE_MODEL))
        answer = {**answer, "spent": True, "checked_at": _now(now).isoformat()}
        _state.update(answer=answer, at=_now(now))
    log.info("Claude probe: %s%s", answer["claude"],
             f" — {answer['detail']}" if answer.get("detail") else "")
    return answer


def forget() -> None:
    """Drop the kept answer (and the lock, bound to its event loop)."""
    _state.clear()
