"""Tests for application/events/bus.py."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.events import CycleCompleted, CycleStarted
from theswarm.domain.events import DomainEvent


class TestEventBus:
    def test_handler_count_empty(self):
        bus = EventBus()
        assert bus.handler_count == 0

    def test_subscribe(self):
        bus = EventBus()

        async def handler(event: DomainEvent) -> None:
            pass

        bus.subscribe(CycleStarted, handler)
        assert bus.handler_count == 1

    def test_subscribe_all(self):
        bus = EventBus()

        async def handler(event: DomainEvent) -> None:
            pass

        bus.subscribe_all(handler)
        assert bus.handler_count == 1

    async def test_publish_to_specific_handler(self):
        bus = EventBus()
        received = []

        async def handler(event: DomainEvent) -> None:
            received.append(event)

        bus.subscribe(CycleStarted, handler)
        event = CycleStarted(project_id="p1")
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].project_id == "p1"

    async def test_publish_does_not_trigger_wrong_type(self):
        bus = EventBus()
        received = []

        async def handler(event: DomainEvent) -> None:
            received.append(event)

        bus.subscribe(CycleStarted, handler)
        await bus.publish(CycleCompleted(project_id="p1"))

        assert len(received) == 0

    async def test_global_handler_receives_all(self):
        bus = EventBus()
        received = []

        async def handler(event: DomainEvent) -> None:
            received.append(event)

        bus.subscribe_all(handler)
        await bus.publish(CycleStarted(project_id="p1"))
        await bus.publish(CycleCompleted(project_id="p2"))

        assert len(received) == 2

    async def test_multiple_handlers(self):
        bus = EventBus()
        count = {"a": 0, "b": 0}

        async def handler_a(event: DomainEvent) -> None:
            count["a"] += 1

        async def handler_b(event: DomainEvent) -> None:
            count["b"] += 1

        bus.subscribe(CycleStarted, handler_a)
        bus.subscribe(CycleStarted, handler_b)
        await bus.publish(CycleStarted(project_id="p1"))

        assert count["a"] == 1
        assert count["b"] == 1

    async def test_handler_error_does_not_break_others(self):
        bus = EventBus()
        received = []

        async def bad_handler(event: DomainEvent) -> None:
            raise RuntimeError("boom")

        async def good_handler(event: DomainEvent) -> None:
            received.append(event)

        bus.subscribe(CycleStarted, bad_handler)
        bus.subscribe(CycleStarted, good_handler)
        await bus.publish(CycleStarted(project_id="p1"))

        assert len(received) == 1

    async def test_publish_no_handlers(self):
        bus = EventBus()
        # Should not raise
        await bus.publish(CycleStarted(project_id="p1"))

    def test_unsubscribe(self):
        bus = EventBus()

        async def handler(event: DomainEvent) -> None:
            pass

        bus.subscribe(CycleStarted, handler)
        assert bus.handler_count == 1

        bus.unsubscribe(CycleStarted, handler)
        assert bus.handler_count == 0

    def test_unsubscribe_nonexistent(self):
        bus = EventBus()

        async def handler(event: DomainEvent) -> None:
            pass

        # Should not raise
        bus.unsubscribe(CycleStarted, handler)

    def test_unsubscribe_all(self):
        bus = EventBus()

        async def handler(event: DomainEvent) -> None:
            pass

        bus.subscribe_all(handler)
        bus.unsubscribe_all(handler)
        assert bus.handler_count == 0

    def test_unsubscribe_all_nonexistent(self):
        bus = EventBus()

        async def handler(event: DomainEvent) -> None:
            pass

        bus.unsubscribe_all(handler)

    def test_clear(self):
        bus = EventBus()

        async def h1(e: DomainEvent) -> None: pass
        async def h2(e: DomainEvent) -> None: pass

        bus.subscribe(CycleStarted, h1)
        bus.subscribe_all(h2)
        assert bus.handler_count == 2

        bus.clear()
        assert bus.handler_count == 0
