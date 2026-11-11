"""Where a live cycle is, in one line a card can carry.

The theater draws a whole stage for one cycle. The home and a project's
banner list several, and said only "running since 08:43 UTC" (the owner,
2026-11-11: "je n'arrive pas à savoir où ça en est, si c'est bloqué, si ça
travaille"). This reads what the process already holds — the phases the
cycle announced, each agent's last telling words (`progress_bridge`) — and
answers: the step, who works, what they last said, how long ago, and
whether that is long enough to say so. No database, no GitHub: a page that
lists ten cycles pays nothing for it.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# Nothing told for this long is said on the card ("quiet for 6 min"), not
# hidden: a Dev's test run or a review of a large diff can take that long,
# and so can a call that hangs — the owner judges, the card does not lie.
QUIET_AFTER_SECONDS = 300
# The watchdog's own idle bound (`application/services/watchdog.py`): past it
# the card says so in the colour of a problem. It still judges nothing.
STALLED_AFTER_SECONDS = 720
SAYS_MAX = 120
ROLE_NAMES = {"po": "Product Owner", "techlead": "Tech Lead", "dev": "Developer", "qa": "QA", "devops": "DevOps"}


def ago(seconds: float) -> str:
    """12 s · 5 min · 1 h 06 — how long, at a glance."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def _empty(status: str) -> dict:
    return {"status": status, "step": "", "step_time": "", "steps": [], "agent": "", "says": "", "ago": "", "quiet": False,
            "stalled": False}


def live_line(record, *, phases: list[dict] | None = None, progress: list[dict] | None = None,
              now: float | None = None) -> dict:
    """The line for one cycle; a cycle that is not running has none.

    `phases` and `progress` default to the process's own history of the
    cycle (`get_phase_history`, `get_live_progress`: newest first). Never
    raises: a card without its line is still a card.
    """
    status = getattr(getattr(record, "status", None), "value", "") or ""
    if status != "running":
        return _empty(status)
    try:
        return _line(record, phases, progress, time.time() if now is None else now)
    except Exception:  # noqa: BLE001 — the page stays
        log.exception("live line: reading cycle %s failed", getattr(record, "id", "?"))
        return _empty(status)


def _line(record, phases: list[dict] | None, progress: list[dict] | None, now: float) -> dict:
    from theswarm.application.services.progress_bridge import PHASE_OWNER, get_live_progress, get_phase_history
    from theswarm.presentation.web.routes.stage import _normalize_role
    from theswarm.presentation.web.routes.theater import steps_from_history

    phases = get_phase_history(record.id) if phases is None else phases
    progress = get_live_progress(record.id) if progress is None else progress
    phases = [p for p in phases if isinstance(p, dict) and p.get("phase")]
    told = [(_normalize_role(str(p.get("role") or "")) or "", str(p.get("message") or ""), float(p.get("ts") or 0))
            for p in progress if isinstance(p, dict)]

    steps = steps_from_history(phases, "running", now=now) if phases else []
    live = next((s for s in reversed(steps) if s["state"] == "live"), None)
    role = PHASE_OWNER.get(live["key"], "") if live else ""
    mine = next((t for t in told if t[0] == role), None) if role else (told[0] if told else None)
    if not role and mine is not None:
        role = mine[0]
    step_started = float(phases[-1].get("ts") or 0) if phases else 0.0
    heard = max(step_started, mine[2] if mine else 0.0)
    silent = now - heard if heard else 0.0
    return {
        "status": "running",
        "step": live["label"] if live else "",
        "step_time": live["time"] if live else "",
        "steps": [{"label": s["label"], "state": s["state"]} for s in steps],
        "agent": ROLE_NAMES.get(role, ""),
        "says": (mine[1] if mine else "")[:SAYS_MAX],
        "ago": ago(silent) if heard else "",
        "quiet": bool(heard) and silent >= QUIET_AFTER_SECONDS,
        "stalled": bool(heard) and silent >= STALLED_AFTER_SECONDS,
    }
