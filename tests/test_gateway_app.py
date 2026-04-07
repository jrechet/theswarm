"""Tests for theswarm.gateway.app — SwarmGateway core, delegation methods, health."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from theswarm_common.models import AgentEvent


# ── Basic construction ───────────────────────────────────────────────


def test_gateway_has_callback_token(gateway):
    assert len(gateway.callback_token) > 20


def test_gateway_registers_handlers(gateway):
    handler = AsyncMock()
    gateway.register("test_event", handler)
    assert handler in gateway._handlers["test_event"]


async def test_route_event_dispatches(gateway):
    handler = AsyncMock()
    gateway.register("test_event", handler)

    event = AgentEvent(event_type="test_event", source="test", payload={"key": "val"})
    await gateway.route_event(event)

    handler.assert_awaited_once_with(event)


async def test_route_event_handles_error(gateway):
    handler = AsyncMock(side_effect=RuntimeError("boom"))
    gateway.register("test_event", handler)

    event = AgentEvent(event_type="test_event", source="test", payload={})
    # Should not raise
    await gateway.route_event(event)


# ── Health endpoint ──────────────────────────────────────────────────


async def test_health_disabled(gateway):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=gateway.app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["bots"]["swarm_po"] == "disabled"


async def test_health_running(gateway):
    gateway._swarm_po_chat = MagicMock()
    gateway._swarm_po_cycle_running = True
    gateway._swarm_po_current_phase = "dev_loop"
    gateway._swarm_po_vcs_map = {"owner/repo": MagicMock()}
    gateway._swarm_po_default_repo = "owner/repo"

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=gateway.app), base_url="http://test") as client:
        resp = await client.get("/health")
    data = resp.json()
    assert "dev_loop" in data["bots"]["swarm_po"]
    assert "owner/repo" in data["repos"]


# ── route_dm_event ───────────────────────────────────────────────────


async def test_route_dm_non_swarm_po(gateway):
    """Non-swarm_po bot name is ignored."""
    with patch("theswarm.persona.handle_dm") as mock_handle:
        await gateway.route_dm_event("other_bot", "hello", "user1")
    mock_handle.assert_not_called()


async def test_route_dm_no_chat(gateway):
    """DM without chat configured logs warning and returns."""
    gateway._nlu = MagicMock()
    gateway._swarm_po_chat = None
    await gateway.route_dm_event("swarm_po", "hello", "user1")


async def test_route_dm_success(gateway):
    gateway._swarm_po_chat = AsyncMock()
    gateway._nlu = MagicMock()

    with patch("theswarm.persona.handle_dm", new_callable=AsyncMock) as mock_handle:
        await gateway.route_dm_event("swarm_po", "status", "user1")
    mock_handle.assert_awaited_once()


# ── Delegation methods ───────────────────────────────────────────────


async def test_wire_swarm_po_delegates(gateway):
    with patch("theswarm.gateway.wiring.wire_swarm_po") as mock_wire:
        gateway.wire_swarm_po(vcs_map={}, default_repo="a/b", chat=None, team_chat=None)
    mock_wire.assert_called_once()


async def test_generate_stories_delegates(gateway):
    with patch("theswarm.gateway.stories.generate_stories", new_callable=AsyncMock, return_value=[]) as mock_gen:
        result = await gateway.swarm_po_generate_stories("test desc")
    assert result == []
    mock_gen.assert_awaited_once()


async def test_store_pending_stories_delegates(gateway):
    with patch("theswarm.gateway.stories.store_pending_stories", new_callable=AsyncMock, return_value="abc") as mock_store:
        result = await gateway.swarm_po_store_pending_stories("u1", [])
    assert result == "abc"


async def test_run_swarm_cycle_delegates(gateway):
    with patch("theswarm.gateway.cycle_runner.run_swarm_cycle", new_callable=AsyncMock) as mock_run:
        await gateway.run_swarm_cycle("u1", "owner/repo")
    mock_run.assert_awaited_once()


async def test_get_plan_delegates(gateway):
    with patch("theswarm.gateway.queries.get_plan", new_callable=AsyncMock, return_value="plan text") as mock_plan:
        result = await gateway.swarm_po_get_plan()
    assert result == "plan text"


async def test_get_report_delegates(gateway):
    with patch("theswarm.gateway.queries.get_report", new_callable=AsyncMock, return_value="report") as mock_report:
        result = await gateway.swarm_po_get_report()
    assert result == "report"


async def test_list_issues_delegates(gateway):
    with patch("theswarm.gateway.queries.list_issues", new_callable=AsyncMock, return_value=[]) as mock_issues:
        result = await gateway.swarm_po_list_issues()
    assert result == []


# ── Utility methods ──────────────────────────────────────────────────


def test_is_cycle_running(gateway):
    assert gateway.swarm_po_is_cycle_running() is False
    gateway._swarm_po_cycle_running = True
    assert gateway.swarm_po_is_cycle_running() is True


def test_current_phase(gateway):
    assert gateway.swarm_po_current_phase() == "unknown"
    gateway._swarm_po_current_phase = "qa"
    assert gateway.swarm_po_current_phase() == "qa"
