"""F1a — verify DemoReady travels EventBus → SSEHub with fields intact."""

from __future__ import annotations

import json

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.events import DemoReady
from theswarm.presentation.web.sse import SSEHub


async def test_demo_ready_roundtrips_through_event_bus_and_sse_hub():
    bus = EventBus()
    hub = SSEHub()
    bus.subscribe_all(hub.broadcast)

    client = hub.connect()

    event = DemoReady(
        cycle_id=CycleId("cycle-xyz"),
        project_id="todo-app",
        report_id="rpt-abc123",
        play_url="/swarm/demos/rpt-abc123/play",
        title="TodoApp — 2026-04-19",
        thumbnail_url="/swarm/artifacts/rpt-abc123/thumb.jpg",
    )
    await bus.publish(event)

    assert not client.empty()
    payload = json.loads(client.get_nowait())

    assert payload["type"] == "DemoReady"
    assert payload["project_id"] == "todo-app"
    assert payload["report_id"] == "rpt-abc123"
    assert payload["play_url"] == "/swarm/demos/rpt-abc123/play"
    assert payload["title"] == "TodoApp — 2026-04-19"
    assert payload["thumbnail_url"] == "/swarm/artifacts/rpt-abc123/thumb.jpg"
    assert payload["cycle_id"] == "cycle-xyz"
    assert payload["event_id"] == event.event_id
    assert payload["occurred_at"] == event.occurred_at.isoformat()


async def test_demo_ready_with_empty_thumbnail_still_serialises():
    bus = EventBus()
    hub = SSEHub()
    bus.subscribe_all(hub.broadcast)
    client = hub.connect()

    await bus.publish(
        DemoReady(
            project_id="p1",
            report_id="r1",
            play_url="/demos/r1/play",
            title="p1 demo",
        )
    )

    payload = json.loads(client.get_nowait())
    assert payload["type"] == "DemoReady"
    assert payload["thumbnail_url"] == ""
    assert payload["play_url"] == "/demos/r1/play"
