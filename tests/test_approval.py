"""Tests for the SwarmPO approval button callback flow.

Proves whether the Approve/Cancel buttons work end-to-end:
callback URL → action extraction → pending lookup → issue creation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm_common.models import AgentEvent
from theswarm.gateway import SwarmGateway


class _FakeSwarmPoConfig:
    enabled = True
    github_repo = "test/repo"
    team_channel = "swarm-team"
    channel = "swarm-bots-logs"
    mm_token = ""


class _FakeAgents:
    swarm_po = _FakeSwarmPoConfig()


class _FakeServer:
    host = "0.0.0.0"
    port = 8091


class _FakeSettings:
    agents = _FakeAgents()
    server = _FakeServer()


@pytest.fixture
def gateway():
    gw = SwarmGateway(_FakeSettings())
    return gw


@pytest.fixture
def wired_gateway(gateway):
    """Gateway with SwarmPO wired and a pending approval."""
    chat = AsyncMock()
    team_chat = AsyncMock()
    vcs = MagicMock()

    issue = MagicMock()
    issue.number = 42
    issue.html_url = "https://github.com/test/42"
    vcs.create_issue.return_value = issue

    gateway.wire_swarm_po(
        vcs_map={"test/repo": vcs},
        default_repo="test/repo",
        chat=chat,
        team_chat=team_chat,
    )

    return gateway, chat, vcs


# ─── Test 1: Happy path — approve creates issues ─────────────────────────────

@pytest.mark.asyncio
async def test_swarm_po_approve_creates_issues(wired_gateway):
    """Clicking Approve triggers issue creation from pending stories."""
    gw, chat, vcs = wired_gateway

    # Simulate: PO generated stories and stored them
    stories = [
        {"title": "US: Build login page", "description": "As a user..."},
        {"title": "US: Add logout button", "description": "As a user..."},
    ]
    pending_id = await gw.swarm_po_store_pending_stories("user123", stories)

    # Simulate: Mattermost sends callback when user clicks Approve
    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": f"swarm_po_approve:{pending_id}",
            "post_id": "post_abc",
            "context": {"action_id": f"swarm_po_approve:{pending_id}"},
        },
    )
    await gw.route_event(event)

    # Verify: issues were created
    assert vcs.create_issue.call_count == 2
    # Verify: confirmation DM sent
    chat.post_dm.assert_called()


@pytest.mark.asyncio
async def test_swarm_po_reject_cancels(wired_gateway):
    """Clicking Cancel sends cancellation message, no issues created."""
    gw, chat, vcs = wired_gateway

    stories = [{"title": "US: Something", "description": "desc"}]
    pending_id = await gw.swarm_po_store_pending_stories("user123", stories)

    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": f"swarm_po_reject:{pending_id}",
            "post_id": "post_abc",
            "context": {"action_id": f"swarm_po_reject:{pending_id}"},
        },
    )
    await gw.route_event(event)

    # No issues created
    vcs.create_issue.assert_not_called()
    # Cancellation message sent
    chat.post_dm.assert_called_once()
    assert "cancelled" in chat.post_dm.call_args[0][1].lower()


# ─── Test 2: Orphaned button — server restarted, pending lost ─────────────────

@pytest.mark.asyncio
async def test_swarm_po_approve_after_restart_is_orphaned(wired_gateway):
    """After server restart, old buttons silently fail (no pending state)."""
    gw, chat, vcs = wired_gateway

    # Don't store any pending stories — simulates restart
    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": "swarm_po_approve:deadbeef",
            "post_id": "post_old",
            "context": {"action_id": "swarm_po_approve:deadbeef"},
        },
    )
    await gw.route_event(event)

    # Nothing happens — no issues, no DM
    vcs.create_issue.assert_not_called()
    chat.post_dm.assert_not_called()


# ─── Test 3: Double-click — pending consumed on first click ───────────────────

@pytest.mark.asyncio
async def test_swarm_po_double_click_is_idempotent(wired_gateway):
    """Clicking Approve twice only creates issues once (pending is popped)."""
    gw, chat, vcs = wired_gateway

    stories = [{"title": "US: Build login", "description": "desc"}]
    pending_id = await gw.swarm_po_store_pending_stories("user123", stories)

    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": f"swarm_po_approve:{pending_id}",
            "post_id": "post_abc",
            "context": {"action_id": f"swarm_po_approve:{pending_id}"},
        },
    )

    # First click
    await gw.route_event(event)
    assert vcs.create_issue.call_count == 1

    # Second click — should be a no-op
    vcs.create_issue.reset_mock()
    await gw.route_event(event)
    vcs.create_issue.assert_not_called()


# ─── Test 4: Callback URL correctness ────────────────────────────────────────

@pytest.mark.asyncio
async def test_callback_url_uses_external_url():
    """post_interactive builds callback URL from external_url config."""
    from theswarm_common.chat.mattermost import MattermostAdapter
    from theswarm_common.config import MattermostConfig, ServerConfig

    mm_config = MattermostConfig(
        base_url="https://chat.test.com",
        bot_token="test-token",
        channel_name="test",
    )
    server_config = ServerConfig(
        host="0.0.0.0",
        port=8090,
        external_url="https://bots.jrec.fr",
    )
    adapter = MattermostAdapter(mm_config, server_config)
    adapter._channel_id = "ch123"

    mock_driver = MagicMock()
    mock_driver.posts.create_post.return_value = {"id": "post789"}
    adapter._driver = mock_driver

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch(
        "theswarm_common.chat.mattermost.asyncio.to_thread",
        side_effect=fake_to_thread,
    ):
        await adapter.post_interactive(
            "test",
            "Approve this?",
            [{"id": "swarm_po_approve:abc123", "name": "Approve", "style": "good"}],
        )

    payload = mock_driver.posts.create_post.call_args[0][0]
    action = payload["props"]["attachments"][0]["actions"][0]

    # Callback URL must use external_url
    assert action["integration"]["url"] == "https://bots.jrec.fr/mattermost/callback"
    # action_id must be in context
    assert action["integration"]["context"]["action_id"] == "swarm_po_approve:abc123"


# ─── Test 5: VCS failure during issue creation ────────────────────────────────

@pytest.mark.asyncio
async def test_swarm_po_approve_vcs_failure_handled(wired_gateway):
    """If VCS fails during issue creation, user gets error feedback."""
    gw, chat, vcs = wired_gateway
    vcs.create_issue.side_effect = Exception("GitHub API down")

    stories = [{"title": "US: Build login", "description": "desc"}]
    pending_id = await gw.swarm_po_store_pending_stories("user123", stories)

    event = AgentEvent(
        event_type="chat_action",
        source="mattermost",
        payload={
            "action_id": f"swarm_po_approve:{pending_id}",
            "post_id": "post_abc",
            "context": {"action_id": f"swarm_po_approve:{pending_id}"},
        },
    )

    # Should not raise — errors are handled gracefully
    await gw.route_event(event)

    # User should get some feedback (either error or partial success)
    chat.post_dm.assert_called()
