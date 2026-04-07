"""Tests for theswarm.gateway.wiring — event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from theswarm_common.models import AgentEvent


@pytest.fixture()
def wired_gateway(gateway):
    """Gateway with wiring applied."""
    chat = AsyncMock()
    team_chat = AsyncMock()
    vcs_map = {"owner/repo": MagicMock()}

    with patch("theswarm.dashboard.get_dashboard_state") as mock_dash:
        mock_dash.return_value = MagicMock()
        from theswarm.gateway.wiring import wire_swarm_po
        wire_swarm_po(gateway, vcs_map, "owner/repo", chat, team_chat)

    return gateway


# ── Chat action handler (approve/cancel) ─────────────────────────────


async def test_action_approve_stories(wired_gateway):
    gw = wired_gateway
    gw._swarm_po_pending_stories["abc123"] = {
        "user_id": "user1",
        "stories": [{"title": "US: Test"}],
    }

    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={"action_id": "swarm_po_approve:abc123"},
    )

    with patch("theswarm.gateway.stories.create_issues", new_callable=AsyncMock) as mock_create:
        await gw.route_event(event)

    mock_create.assert_awaited_once()
    assert "abc123" not in gw._swarm_po_pending_stories


async def test_action_cancel_stories(wired_gateway):
    gw = wired_gateway
    gw._swarm_po_pending_stories["def456"] = {
        "user_id": "user2",
        "stories": [{"title": "US: X"}],
    }

    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={"action_id": "swarm_po_cancel:def456"},
    )

    await gw.route_event(event)
    assert "def456" not in gw._swarm_po_pending_stories
    gw._swarm_po_chat.post_dm.assert_awaited_once()


async def test_action_ignores_non_swarm(wired_gateway):
    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={"action_id": "other_bot:abc"},
    )
    await wired_gateway.route_event(event)  # no error


async def test_action_missing_pending_id(wired_gateway):
    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={"action_id": "swarm_po_approve:missing"},
    )
    await wired_gateway.route_event(event)  # logs warning, no error


# ── Chat message handler (!swarm-po commands) ────────────────────────


async def test_chat_status_idle(wired_gateway):
    gw = wired_gateway
    gw._swarm_po_cycle_running = False

    event = AgentEvent(
        event_type="chat_message",
        source="mattermost",
        payload={"message": "!swarm-po status", "channel_id": "ch1"},
    )
    await gw.route_event(event)

    gw._swarm_po_chat.post_message_to_channel.assert_awaited()
    msg = gw._swarm_po_chat.post_message_to_channel.call_args[0][1]
    assert "Idle" in msg


async def test_chat_status_running(wired_gateway):
    gw = wired_gateway
    gw._swarm_po_cycle_running = True
    gw._swarm_po_current_phase = "dev_loop"

    event = AgentEvent(
        event_type="chat_message",
        source="mattermost",
        payload={"message": "!swarm-po status", "channel_id": "ch1"},
    )
    await gw.route_event(event)

    msg = gw._swarm_po_chat.post_message_to_channel.call_args[0][1]
    assert "dev_loop" in msg


async def test_chat_plan_command(wired_gateway):
    gw = wired_gateway

    with patch.object(gw, "swarm_po_get_plan", new_callable=AsyncMock, return_value="Today's plan"):
        event = AgentEvent(
            event_type="chat_message",
            source="mattermost",
            payload={"message": "!swarm-po plan", "channel_id": "ch1"},
        )
        await gw.route_event(event)

    msg = gw._swarm_po_chat.post_message_to_channel.call_args[0][1]
    assert "Today's plan" in msg


async def test_chat_report_command(wired_gateway):
    gw = wired_gateway

    with patch.object(gw, "swarm_po_get_report", new_callable=AsyncMock, return_value="Daily report"):
        event = AgentEvent(
            event_type="chat_message",
            source="mattermost",
            payload={"message": "!swarm-po report", "channel_id": "ch1"},
        )
        await gw.route_event(event)

    msg = gw._swarm_po_chat.post_message_to_channel.call_args[0][1]
    assert "Daily report" in msg
