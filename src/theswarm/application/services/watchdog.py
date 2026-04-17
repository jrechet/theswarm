"""Idle agent watchdog for autonomous cycle monitoring.

Detects stalled agents by tracking heartbeats emitted from the progress
callback.  Wire into the cycle by calling ``heartbeat()`` from the
``_progress()`` bridge and ``start()``/``stop()`` around the cycle run.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Coroutine

log = logging.getLogger(__name__)


@dataclass
class AgentHeartbeat:
    role: str
    last_activity: float = field(default_factory=time.monotonic)
    last_message: str = ""
    idle_warnings: int = 0


@dataclass(frozen=True)
class WatchdogEvent:
    role: str
    idle_seconds: float
    warning_count: int
    message: str


IdleCallback = Callable[[WatchdogEvent], Coroutine[None, None, None]]


class AgentWatchdog:
    """Monitors agent activity and detects idle/stalled agents.

    Wire into the cycle by calling ``heartbeat()`` from the progress callback
    and ``start()``/``stop()`` around the cycle run.
    """

    def __init__(
        self,
        idle_threshold: float = 720.0,
        check_interval: float = 30.0,
        max_warnings: int = 3,
        on_idle: IdleCallback | None = None,
        on_timeout: IdleCallback | None = None,
    ) -> None:
        self._idle_threshold = idle_threshold
        self._check_interval = check_interval
        self._max_warnings = max_warnings
        self._on_idle = on_idle
        self._on_timeout = on_timeout

        self._agents: dict[str, AgentHeartbeat] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def heartbeat(self, role: str, message: str = "") -> None:
        """Record activity from an agent.  Thread-safe for asyncio tasks."""
        hb = self._agents.get(role)
        if hb is None:
            self._agents[role] = AgentHeartbeat(role=role, last_message=message)
        else:
            hb.last_activity = time.monotonic()
            hb.last_message = message
            hb.idle_warnings = 0

    async def start(self) -> None:
        """Start the watchdog monitor loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the watchdog monitor loop and clean up."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def get_status(self) -> dict[str, dict[str, object]]:
        """Return current status of all monitored agents for API/dashboard."""
        now = time.monotonic()
        return {
            role: {
                "last_activity_ago_s": round(now - hb.last_activity, 1),
                "idle_warnings": hb.idle_warnings,
                "last_message": hb.last_message,
            }
            for role, hb in self._agents.items()
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Periodic check for idle agents."""
        while self._running:
            await asyncio.sleep(self._check_interval)
            now = time.monotonic()

            for hb in list(self._agents.values()):
                idle_seconds = now - hb.last_activity
                if idle_seconds < self._idle_threshold:
                    continue

                hb.idle_warnings += 1
                event = WatchdogEvent(
                    role=hb.role,
                    idle_seconds=round(idle_seconds, 1),
                    warning_count=hb.idle_warnings,
                    message=f"Agent '{hb.role}' idle for {idle_seconds:.0f}s",
                )

                if hb.idle_warnings >= self._max_warnings:
                    log.error(
                        "Agent '%s' timed out after %d warnings (idle %.0fs)",
                        hb.role,
                        hb.idle_warnings,
                        idle_seconds,
                    )
                    if self._on_timeout is not None:
                        await self._on_timeout(event)
                else:
                    log.warning(
                        "Agent '%s' idle for %.0fs (warning %d/%d)",
                        hb.role,
                        idle_seconds,
                        hb.idle_warnings,
                        self._max_warnings,
                    )
                    if self._on_idle is not None:
                        await self._on_idle(event)
