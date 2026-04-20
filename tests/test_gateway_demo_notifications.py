"""F1c — wire_demo_notifications DMs on DemoReady."""

from __future__ import annotations

from unittest.mock import AsyncMock

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.events import DemoReady
from theswarm.gateway.wiring import wire_demo_notifications


async def test_wire_demo_notifications_dms_configured_user():
    bus = EventBus()
    chat = AsyncMock()
    chat.post_dm = AsyncMock(return_value="msg-id")

    wire_demo_notifications(bus, chat, notify_user_id="U12345")

    await bus.publish(
        DemoReady(
            cycle_id=CycleId("c1"),
            project_id="owner/app",
            report_id="rpt-abc",
            play_url="/swarm/demos/rpt-abc/play",
            title="owner/app — 2026-04-19",
            thumbnail_url="",
        )
    )

    chat.post_dm.assert_awaited_once()
    user_id, text = chat.post_dm.await_args.args
    assert user_id == "U12345"
    assert "owner/app — 2026-04-19" in text
    assert "/swarm/demos/rpt-abc/play" in text
    assert text.startswith("🎬 Demo ready")


async def test_wire_demo_notifications_is_noop_without_chat():
    bus = EventBus()

    wire_demo_notifications(bus, chat=None, notify_user_id="U12345")

    await bus.publish(
        DemoReady(
            project_id="p",
            report_id="r",
            play_url="/demos/r/play",
            title="t",
        )
    )


async def test_wire_demo_notifications_is_noop_without_user_id():
    bus = EventBus()
    chat = AsyncMock()
    chat.post_dm = AsyncMock()

    wire_demo_notifications(bus, chat, notify_user_id="")

    await bus.publish(
        DemoReady(
            project_id="p",
            report_id="r",
            play_url="/demos/r/play",
            title="t",
        )
    )

    chat.post_dm.assert_not_called()


async def test_wire_demo_notifications_swallows_chat_errors():
    bus = EventBus()
    chat = AsyncMock()
    chat.post_dm = AsyncMock(side_effect=RuntimeError("mattermost down"))

    wire_demo_notifications(bus, chat, notify_user_id="U1")

    await bus.publish(
        DemoReady(
            project_id="p",
            report_id="r",
            play_url="/demos/r/play",
            title="t",
        )
    )

    chat.post_dm.assert_awaited_once()
