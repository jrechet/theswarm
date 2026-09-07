"""Regression test: a finished agent must stop being watchdog-monitored.

Reproduces prod cycle bc1b1e6abb82: PO kept getting logged as timed out
every 30s long after it had actually finished. Root cause was two-fold —
(1) the watchdog had no way to stop tracking an agent once its phase ended,
so a stale heartbeat aged forever, and (2) even for an agent that is
legitimately idle (not retired), the watchdog re-fired ``on_timeout`` on
every single check_interval once past ``max_warnings`` instead of once per
idle episode. Both are exercised here directly against ``AgentWatchdog``,
without running the full ``run_daily_cycle`` graph.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from theswarm.application.services.watchdog import AgentWatchdog


class TestRetiredAgentStopsBeingMonitored:
    async def test_po_stops_timing_out_after_retire(self):
        on_timeout = AsyncMock()
        wd = AgentWatchdog(
            idle_threshold=0.02,
            check_interval=0.02,
            max_warnings=2,
            on_timeout=on_timeout,
        )

        # PO finishes its phase, then the cycle moves on to TechLead/Dev --
        # exactly like a real cycle, PO never heartbeats again once its
        # phase is done.
        wd.heartbeat("PO", "planning done")
        wd.heartbeat("TechLead", "reviewing plan")
        wd.heartbeat("Dev", "implementing")

        await wd.start()

        # Advance past idle_threshold for `max_warnings` checks so PO's
        # timeout actually fires (locks in the "fires once" fix too).
        await asyncio.sleep(0.25)

        po_timeouts = [c for c in on_timeout.call_args_list if c.args[0].role == "PO"]
        assert len(po_timeouts) >= 1, "expected PO to time out while idle"
        assert "PO" in wd.get_status()

        # The fix under test: the cycle retires PO once its phase ends.
        wd.retire("PO")
        assert "PO" not in wd.get_status()

        calls_at_retire = len(on_timeout.call_args_list)

        # Advance several more check intervals -- a retired agent must
        # never be reported idle/timed-out again.
        await asyncio.sleep(0.25)
        await wd.stop()

        new_po_timeouts = [
            c
            for c in on_timeout.call_args_list[calls_at_retire:]
            if c.args[0].role == "PO"
        ]
        assert new_po_timeouts == []
        assert "PO" not in wd.get_status()


class TestTimeoutFiresOnceNotPerCheckInterval:
    async def test_idle_agent_times_out_exactly_once(self):
        on_timeout = AsyncMock()
        wd = AgentWatchdog(
            idle_threshold=0.02,
            check_interval=0.02,
            max_warnings=2,
            on_timeout=on_timeout,
        )
        wd.heartbeat("PO", "started")

        await wd.start()
        # Long enough for many check intervals past max_warnings -- without
        # the fix this would fire on_timeout once per interval.
        await asyncio.sleep(0.3)
        await wd.stop()

        po_timeouts = [c for c in on_timeout.call_args_list if c.args[0].role == "PO"]
        assert len(po_timeouts) == 1
