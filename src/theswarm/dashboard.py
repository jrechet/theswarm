"""Live cycle state — shared mutable state for real-time cycle tracking.

Used by cycle_runner.py, wiring.py, and the v2 web routes to track
live cycle progress, cost, and events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


class DashboardState:
    """Shared mutable state for the live cycle event feed."""

    def __init__(self) -> None:
        self.cycle_running: bool = False
        self.current_phase: str = ""
        self.current_repo: str = ""
        self.cycle_start: str = ""
        self.cost_so_far: float = 0.0
        self.events: list[dict[str, str]] = []
        self._subscribers: list[asyncio.Queue] = []
        self.github_repo: str = ""  # set by gateway for history queries
        self.reports: dict[str, dict] = {}  # date -> cycle result dict
        self.base_url: str = ""  # external URL for report action endpoints
        self._cycles: dict[str, "CycleLive"] = {}  # each cycle's own state (`for_cycle`)

    def push_event(self, role: str, message: str, cycle_id: str = "") -> None:
        event = {
            "role": role,
            "message": message,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        if cycle_id:
            event["cycle_id"] = cycle_id
        self.events.append(event)
        # Keep last 100 events
        if len(self.events) > 100:
            self.events = self.events[-100:]
        # Notify SSE subscribers
        data = json.dumps(event)
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    def start_cycle(self, repo: str) -> None:
        self.cycle_running = True
        self.current_repo = repo
        self.cycle_start = datetime.now().strftime("%H:%M:%S")
        self.cost_so_far = 0.0
        self.events = []

    def end_cycle(self) -> None:
        self.cycle_running = False
        self.current_phase = ""

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers = [s for s in self._subscribers if s is not q]

    def store_report(self, date: str, result: dict) -> None:
        """Store a cycle result for later report serving."""
        self.reports[date] = result
        # Keep last 30 reports
        if len(self.reports) > 30:
            oldest = sorted(self.reports.keys())[0]
            del self.reports[oldest]

    def for_cycle(self, cycle_id: str, repo: str) -> "CycleLive":
        """This cycle's own live state, started now (defect 12). The state was
        one for the process: two cycles side by side overwrote each other's
        phase, repository and cost, the second to start wiped the first's
        events, and the first to end said nothing was running."""
        live = CycleLive(self, cycle_id, repo)
        self._cycles[cycle_id] = live
        return live

    def to_json(self) -> dict[str, Any]:
        running = [c for c in self._cycles.values() if c.running]
        if not running:  # no cycle of its own is running: the one state, as before (the CLI, the gateway)
            return {
                "cycles": [],
                "cycle_running": self.cycle_running,
                "current_phase": self.current_phase,
                "current_repo": self.current_repo,
                "cycle_start": self.cycle_start,
                "cost_so_far": round(self.cost_so_far, 4),
                "recent_events": self.events[-20:],
            }
        latest = running[-1] if running else None
        return {
            # The fields a single cycle had, read off the last one to start…
            "cycle_running": bool(running),
            "current_phase": latest.current_phase if latest else "",
            "current_repo": latest.repo if latest else "",
            "cycle_start": latest.cycle_start if latest else "",
            "cost_so_far": round(latest.cost_so_far if latest else 0.0, 4),
            "recent_events": self.events[-20:],
            # …and every running cycle by name.
            "cycles": [c.to_json() for c in running],
        }


class CycleLive:
    """One cycle's part of the live state — what the runner and the progress
    bridge write (`current_phase`, `push_event`, `cost_so_far`, `end_cycle`),
    kept apart from every other cycle's."""

    def __init__(self, shared: "DashboardState", cycle_id: str, repo: str) -> None:
        self._shared = shared
        self.cycle_id = cycle_id
        self.repo = repo
        self.running = True
        self.current_phase = ""
        self.cycle_start = datetime.now().strftime("%H:%M:%S")
        self.cost_so_far = 0.0

    def push_event(self, role: str, message: str) -> None:
        self._shared.push_event(role, message, cycle_id=self.cycle_id)

    def store_report(self, date: str, result: dict) -> None:
        self._shared.store_report(date, result)

    def end_cycle(self) -> None:
        self.running = False
        self.current_phase = ""
        finished = [cid for cid, c in self._shared._cycles.items() if not c.running]
        for cid in finished[:-20]:  # the last twenty ended stay readable; the rest go
            self._shared._cycles.pop(cid, None)

    def to_json(self) -> dict[str, Any]:
        return {"cycle_id": self.cycle_id, "repo": self.repo, "current_phase": self.current_phase,
                "cycle_start": self.cycle_start, "cost_so_far": round(self.cost_so_far, 4)}


# Singleton
_state = DashboardState()


def get_dashboard_state() -> DashboardState:
    return _state
