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

    def push_event(self, role: str, message: str) -> None:
        event = {
            "role": role,
            "message": message,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
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

    def to_json(self) -> dict[str, Any]:
        return {
            "cycle_running": self.cycle_running,
            "current_phase": self.current_phase,
            "current_repo": self.current_repo,
            "cycle_start": self.cycle_start,
            "cost_so_far": round(self.cost_so_far, 4),
            "recent_events": self.events[-20:],
        }


# Singleton
_state = DashboardState()


def get_dashboard_state() -> DashboardState:
    return _state
