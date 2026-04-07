"""Tests for the ping/pong interactive button flow.

Covers:
1. Ping intent → interactive buttons posted
2. Pong callback → "Pong!" posted to DM
3. Dismiss callback → no response
4. Full flow: DM → NLU → handler → buttons → callback → response
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm_common.chat import Intent
from theswarm_common.models import AgentEvent


# ── Ping handler ─────────────────────────────────────────────────


async def test_ping_posts_interactive_buttons():
    """Sending 'ping' DM posts a message with Pong and Dismiss buttons."""
    from theswarm.persona import handle_dm

    chat = AsyncMock()
    chat.post_dm_interactive = AsyncMock(return_value="post123")

    nlu = AsyncMock()
    nlu.parse_intent = AsyncMock(return_value=Intent(
        action="ping", params={}, confidence=0.95, raw_text="ping",
    ))

    gateway = MagicMock()

    await handle_dm("ping", "user1", chat, nlu, gateway)

    chat.post_dm_interactive.assert_called_once()
    call_args = chat.post_dm_interactive.call_args
    assert call_args[0][0] == "user1"  # user_id
    assert call_args[0][1]  # has some text

    actions = call_args.kwargs.get("actions") or call_args[0][2]
    assert len(actions) == 2
    assert actions[0]["name"] == "Ping"
    assert actions[0]["id"].startswith("swarm_po_ping:")
    assert actions[1]["name"] == "Pong"
    assert actions[1]["id"].startswith("swarm_po_pong:")


async def test_ping_is_in_known_actions():
    """'ping' must be in KNOWN_ACTIONS for NLU to route to it."""
    from theswarm.persona import KNOWN_ACTIONS
    assert "ping" in KNOWN_ACTIONS


# ── Pong callback ────────────────────────────────────────────────


async def test_pong_callback_posts_pong(gateway):
    """Clicking the Pong button posts 'pong' to the user's DM."""
    from theswarm.gateway.wiring import wire_swarm_po

    chat = AsyncMock()
    team_chat = AsyncMock()
    vcs_map = {"owner/repo": MagicMock()}

    wire_swarm_po(gateway, vcs_map, "owner/repo", chat, team_chat)

    # Simulate Mattermost callback for pong button
    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": "swarm_po_pong:ping",
            "post_id": "post123",
            "user_id": "user1",
            "context": {"action_id": "swarm_po_pong:ping"},
        },
    )
    await gateway.route_event(event)

    chat.post_dm.assert_called_once_with("user1", "pong")


async def test_ping_callback_posts_ping(gateway):
    """Clicking the Ping button posts 'ping' to the user's DM."""
    from theswarm.gateway.wiring import wire_swarm_po

    chat = AsyncMock()
    team_chat = AsyncMock()
    vcs_map = {"owner/repo": MagicMock()}

    wire_swarm_po(gateway, vcs_map, "owner/repo", chat, team_chat)

    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": "swarm_po_ping:ping",
            "post_id": "post123",
            "user_id": "user1",
            "context": {"action_id": "swarm_po_ping:ping"},
        },
    )
    await gateway.route_event(event)

    chat.post_dm.assert_called_once_with("user1", "ping")


async def test_dismiss_callback_is_silent(gateway):
    """Clicking the Dismiss button does nothing."""
    from theswarm.gateway.wiring import wire_swarm_po

    chat = AsyncMock()
    team_chat = AsyncMock()
    vcs_map = {"owner/repo": MagicMock()}

    wire_swarm_po(gateway, vcs_map, "owner/repo", chat, team_chat)

    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": "swarm_po_dismiss:ping",
            "post_id": "post123",
            "user_id": "user1",
            "context": {"action_id": "swarm_po_dismiss:ping"},
        },
    )
    await gateway.route_event(event)

    chat.post_dm.assert_not_called()


# ── Full flow ────────────────────────────────────────────────────


async def test_full_ping_pong_flow(gateway):
    """Full flow: ping DM → interactive buttons → pong callback → response."""
    from theswarm.gateway.wiring import wire_swarm_po
    from theswarm.persona import handle_dm

    chat = AsyncMock()
    chat.post_dm_interactive = AsyncMock(return_value="post123")
    team_chat = AsyncMock()
    vcs_map = {"owner/repo": MagicMock()}

    wire_swarm_po(gateway, vcs_map, "owner/repo", chat, team_chat)

    nlu = AsyncMock()
    nlu.parse_intent = AsyncMock(return_value=Intent(
        action="ping", params={}, confidence=0.95, raw_text="ping",
    ))
    gateway._nlu = nlu

    # Step 1: User sends "ping" DM
    await handle_dm("ping", "user1", chat, nlu, gateway)

    # Verify buttons were posted
    assert chat.post_dm_interactive.call_count == 1
    call_args = chat.post_dm_interactive.call_args
    actions = call_args.kwargs.get("actions") or call_args[0][2]
    pong_action_id = actions[1]["id"]
    assert pong_action_id.startswith("swarm_po_pong:")

    # Step 2: User clicks Pong button → Mattermost sends callback
    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": pong_action_id,
            "post_id": "post123",
            "user_id": "user1",
            "context": {"action_id": pong_action_id},
        },
    )
    await gateway.route_event(event)

    # Step 3: Verify "pong" was posted
    chat.post_dm.assert_called_once_with("user1", "pong")
