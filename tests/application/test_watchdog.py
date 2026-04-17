"""Tests for application/services/watchdog.py."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from theswarm.application.services.watchdog import (
    AgentHeartbeat,
    AgentWatchdog,
    WatchdogEvent,
)


class TestAgentHeartbeat:
    def test_defaults(self):
        hb = AgentHeartbeat(role="dev")
        assert hb.role == "dev"
        assert hb.last_message == ""
        assert hb.idle_warnings == 0
        assert hb.last_activity > 0


class TestWatchdogEvent:
    def test_frozen(self):
        event = WatchdogEvent(role="dev", idle_seconds=100.0, warning_count=1, message="idle")
        assert event.role == "dev"
        with pytest.raises(AttributeError):
            event.role = "qa"  # type: ignore[misc]


class TestHeartbeat:
    def test_heartbeat_creates_entry(self):
        wd = AgentWatchdog()
        wd.heartbeat("dev", "working on task")

        status = wd.get_status()
        assert "dev" in status
        assert status["dev"]["last_message"] == "working on task"
        assert status["dev"]["idle_warnings"] == 0

    def test_heartbeat_updates_existing(self):
        wd = AgentWatchdog()
        wd.heartbeat("dev", "first")
        first_status = wd.get_status()

        wd.heartbeat("dev", "second")
        second_status = wd.get_status()

        assert second_status["dev"]["last_message"] == "second"
        assert second_status["dev"]["last_activity_ago_s"] <= first_status["dev"]["last_activity_ago_s"]

    def test_heartbeat_resets_warnings(self):
        wd = AgentWatchdog()
        wd.heartbeat("dev")
        # Manually bump warnings to simulate idle detection
        wd._agents["dev"].idle_warnings = 2

        wd.heartbeat("dev", "back to work")
        assert wd._agents["dev"].idle_warnings == 0

    def test_multiple_agents(self):
        wd = AgentWatchdog()
        wd.heartbeat("dev", "coding")
        wd.heartbeat("qa", "testing")

        status = wd.get_status()
        assert len(status) == 2
        assert "dev" in status
        assert "qa" in status


class TestGetStatus:
    def test_empty(self):
        wd = AgentWatchdog()
        assert wd.get_status() == {}

    def test_format(self):
        wd = AgentWatchdog()
        wd.heartbeat("dev", "working")

        status = wd.get_status()
        entry = status["dev"]
        assert isinstance(entry["last_activity_ago_s"], float)
        assert isinstance(entry["idle_warnings"], int)
        assert isinstance(entry["last_message"], str)


class TestIdleDetection:
    async def test_idle_fires_on_idle_callback(self):
        on_idle = AsyncMock()
        wd = AgentWatchdog(
            idle_threshold=0.05,
            check_interval=0.02,
            on_idle=on_idle,
        )
        wd.heartbeat("dev", "started")

        await wd.start()
        await asyncio.sleep(0.15)
        await wd.stop()

        assert on_idle.call_count >= 1
        event = on_idle.call_args[0][0]
        assert isinstance(event, WatchdogEvent)
        assert event.role == "dev"
        assert event.idle_seconds > 0
        assert event.warning_count >= 1

    async def test_no_callback_when_active(self):
        on_idle = AsyncMock()
        wd = AgentWatchdog(
            idle_threshold=1.0,
            check_interval=0.02,
            on_idle=on_idle,
        )
        wd.heartbeat("dev", "started")

        await wd.start()
        # Keep sending heartbeats faster than the threshold
        for _ in range(5):
            await asyncio.sleep(0.02)
            wd.heartbeat("dev", "still working")
        await wd.stop()

        on_idle.assert_not_called()


class TestTimeoutDetection:
    async def test_max_warnings_triggers_on_timeout(self):
        on_idle = AsyncMock()
        on_timeout = AsyncMock()
        wd = AgentWatchdog(
            idle_threshold=0.02,
            check_interval=0.02,
            max_warnings=2,
            on_idle=on_idle,
            on_timeout=on_timeout,
        )
        wd.heartbeat("dev", "started")

        await wd.start()
        await asyncio.sleep(0.25)
        await wd.stop()

        assert on_timeout.call_count >= 1
        event = on_timeout.call_args[0][0]
        assert event.warning_count >= 2


class TestLifecycle:
    async def test_start_stop(self):
        wd = AgentWatchdog(check_interval=0.01)

        await wd.start()
        assert wd._running is True
        assert wd._task is not None

        await wd.stop()
        assert wd._running is False
        assert wd._task is None

    async def test_double_start_is_safe(self):
        wd = AgentWatchdog(check_interval=0.01)

        await wd.start()
        task = wd._task
        await wd.start()  # Should not create a second task
        assert wd._task is task

        await wd.stop()

    async def test_stop_without_start(self):
        wd = AgentWatchdog()
        # Should not raise
        await wd.stop()

    async def test_stop_cancels_task(self):
        wd = AgentWatchdog(check_interval=0.01)

        await wd.start()
        task = wd._task
        await wd.stop()

        assert task is not None
        assert task.cancelled() or task.done()
