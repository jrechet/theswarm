"""Tests for theswarm.dashboard — DashboardState lifecycle and SSE queue management."""

from __future__ import annotations

import asyncio
import json

from theswarm.dashboard import DashboardState


class TestPushEvent:
    def test_adds_event(self):
        state = DashboardState()

        state.push_event("dev", "Started implementation")

        assert len(state.events) == 1
        assert state.events[0]["role"] == "dev"
        assert state.events[0]["message"] == "Started implementation"
        assert "timestamp" in state.events[0]

    def test_caps_at_100(self):
        state = DashboardState()

        for i in range(120):
            state.push_event("dev", f"Event {i}")

        assert len(state.events) == 100
        # Oldest events trimmed — last event should be the most recent
        assert state.events[-1]["message"] == "Event 119"
        assert state.events[0]["message"] == "Event 20"

    def test_notifies_subscribers(self):
        state = DashboardState()
        queue = state.subscribe()

        state.push_event("qa", "Tests passed")

        assert not queue.empty()
        data = json.loads(queue.get_nowait())
        assert data["role"] == "qa"
        assert data["message"] == "Tests passed"


class TestCycleLifecycle:
    def test_start_cycle(self):
        state = DashboardState()

        state.start_cycle("owner/repo")

        assert state.cycle_running is True
        assert state.current_repo == "owner/repo"
        assert state.cycle_start != ""
        assert state.cost_so_far == 0.0
        assert state.events == []

    def test_end_cycle(self):
        state = DashboardState()
        state.start_cycle("owner/repo")
        state.current_phase = "development"

        state.end_cycle()

        assert state.cycle_running is False
        assert state.current_phase == ""

    def test_start_clears_previous_events(self):
        state = DashboardState()
        state.push_event("dev", "old event")
        assert len(state.events) == 1

        state.start_cycle("owner/repo")

        assert state.events == []


class TestToJson:
    def test_shape(self):
        state = DashboardState()
        state.start_cycle("owner/repo")
        state.current_phase = "development"
        state.cost_so_far = 1.2345

        result = state.to_json()

        assert result["cycle_running"] is True
        assert result["current_phase"] == "development"
        assert result["current_repo"] == "owner/repo"
        assert result["cost_so_far"] == 1.2345
        assert "cycle_start" in result
        assert "recent_events" in result
        assert isinstance(result["recent_events"], list)

    def test_recent_events_limited_to_20(self):
        state = DashboardState()
        for i in range(30):
            state.push_event("dev", f"Event {i}")

        result = state.to_json()

        assert len(result["recent_events"]) == 20

    def test_cost_rounded(self):
        state = DashboardState()
        state.cost_so_far = 1.23456789

        result = state.to_json()

        assert result["cost_so_far"] == 1.2346


class TestSubscribeUnsubscribe:
    def test_subscribe_returns_queue(self):
        state = DashboardState()

        queue = state.subscribe()

        assert isinstance(queue, asyncio.Queue)
        assert len(state._subscribers) == 1

    def test_multiple_subscribers(self):
        state = DashboardState()

        q1 = state.subscribe()
        q2 = state.subscribe()

        assert len(state._subscribers) == 2

        state.push_event("po", "Plan ready")

        assert not q1.empty()
        assert not q2.empty()

    def test_unsubscribe_removes_queue(self):
        state = DashboardState()
        q1 = state.subscribe()
        q2 = state.subscribe()

        state.unsubscribe(q1)

        assert len(state._subscribers) == 1
        assert state._subscribers[0] is q2

    def test_unsubscribe_nonexistent_is_safe(self):
        state = DashboardState()
        orphan_queue: asyncio.Queue = asyncio.Queue()

        # Should not raise
        state.unsubscribe(orphan_queue)

        assert len(state._subscribers) == 0

    def test_full_queue_does_not_raise(self):
        state = DashboardState()
        queue = state.subscribe()
        # Fill the queue (maxsize=50)
        for i in range(50):
            queue.put_nowait(f"data-{i}")

        # Should not raise even though queue is full
        state.push_event("dev", "overflow event")

        # Queue still has 50 items (the new one was dropped)
        assert queue.qsize() == 50
