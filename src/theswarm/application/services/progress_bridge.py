"""Bridge: translate on_progress callbacks into v2 domain events.

cycle.py emits ``on_progress(role, message)`` callbacks.  This bridge
publishes them as domain events on the EventBus so that the SSE pipeline
(EventBus -> SSEHub -> /api/events -> browser) receives live data.

It also forwards calls to the legacy DashboardState for backward
compatibility with the Mattermost event path, and stashes the latest
message per (cycle, role) in a process-local cache so the cycle detail
page can render a "live progress" panel without persisting every event.
"""

from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.events import (
    AgentActivity,
    CycleCompleted,
    CycleFailed,
    PhaseChanged,
)
from theswarm.domain.cycles.value_objects import CycleId

log = logging.getLogger(__name__)

_PR_OPENED_RE = re.compile(r"PR #(\d+) opened")
_PR_DECISION_RE = re.compile(r"PR #(\d+): (\w+)")


# In-process cache: latest progress message keyed by (cycle_id, role).
# Capped to avoid unbounded growth across long-running prod processes.
_LIVE_PROGRESS: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
_LIVE_PROGRESS_MAX = 500


def record_live_progress(cycle_id: str, role: str, message: str) -> None:
    """Stash the latest progress message for (cycle_id, role)."""
    key = (cycle_id, role)
    if key in _LIVE_PROGRESS:
        _LIVE_PROGRESS.move_to_end(key)
    _LIVE_PROGRESS[key] = {
        "message": message,
        "ts": time.time(),
    }
    while len(_LIVE_PROGRESS) > _LIVE_PROGRESS_MAX:
        _LIVE_PROGRESS.popitem(last=False)


def get_live_progress(cycle_id: str) -> list[dict]:
    """Return latest message per role for a cycle, ordered by recency."""
    rows: list[dict] = []
    for (cid, role), payload in reversed(_LIVE_PROGRESS.items()):
        if cid != cycle_id:
            continue
        rows.append({
            "role": role,
            "message": payload["message"],
            "ts": payload["ts"],
        })
    return rows


class ProgressBridge:
    """Translate ``on_progress(role, message)`` into domain events."""

    def __init__(
        self,
        event_bus: EventBus,
        cycle_id: str,
        project_id: str,
        dashboard_state: object | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._cycle_id = CycleId(cycle_id)
        self._project_id = project_id
        self._dashboard_state = dashboard_state
        self._current_agent: str = ""

    async def __call__(self, role: str, message: str) -> None:
        """Handle an on_progress callback from cycle.py."""
        # Stash for the live-progress panel.
        record_live_progress(str(self._cycle_id), role, message)

        # Forward to legacy DashboardState (Mattermost path)
        if self._dashboard_state is not None:
            ds = self._dashboard_state
            if hasattr(ds, "current_phase"):
                ds.current_phase = f"{role}: {message[:50]}"  # type: ignore[attr-defined]
            if hasattr(ds, "push_event"):
                ds.push_event(role, message)  # type: ignore[attr-defined]

        # Detect phase changes (new agent starting work)
        if role != self._current_agent:
            self._current_agent = role
            await self._event_bus.publish(
                PhaseChanged(
                    cycle_id=self._cycle_id,
                    project_id=self._project_id,
                    phase=message[:80],
                    agent=role,
                )
            )
            return

        # Detect PR events
        pr_match = _PR_OPENED_RE.search(message)
        if pr_match:
            await self._event_bus.publish(
                AgentActivity(
                    cycle_id=self._cycle_id,
                    project_id=self._project_id,
                    agent=role,
                    action="pr_opened",
                    detail=message,
                    metadata={"pr_number": int(pr_match.group(1))},
                )
            )
            return

        review_match = _PR_DECISION_RE.search(message)
        if review_match:
            await self._event_bus.publish(
                AgentActivity(
                    cycle_id=self._cycle_id,
                    project_id=self._project_id,
                    agent=role,
                    action="review",
                    detail=message,
                    metadata={
                        "pr_number": int(review_match.group(1)),
                        "decision": review_match.group(2),
                    },
                )
            )
            return

        # General progress
        await self._event_bus.publish(
            AgentActivity(
                cycle_id=self._cycle_id,
                project_id=self._project_id,
                agent=role,
                action="progress",
                detail=message,
            )
        )
