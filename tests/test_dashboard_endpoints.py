"""Tests for dashboard HTTP endpoints and SSE."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI


@pytest.fixture()
def dashboard_app():
    """Return a fresh FastAPI app with dashboard routes registered."""
    app = FastAPI()
    from theswarm.dashboard import register_dashboard_routes
    register_dashboard_routes(app)
    return app


async def test_dashboard_page(dashboard_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=dashboard_app), base_url="http://test") as client:
        resp = await client.get("/swarm/dashboard")

    assert resp.status_code == 200
    assert "TheSwarm Dashboard" in resp.text
    assert "text/html" in resp.headers["content-type"]


async def test_dashboard_state_idle(dashboard_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=dashboard_app), base_url="http://test") as client:
        resp = await client.get("/swarm/dashboard/state")

    data = resp.json()
    assert data["cycle_running"] is False
    assert data["cost_so_far"] == 0.0


async def test_dashboard_state_running(dashboard_app):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.start_cycle("owner/repo")
    state.current_phase = "dev_loop"
    state.cost_so_far = 1.5

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=dashboard_app), base_url="http://test") as client:
        resp = await client.get("/swarm/dashboard/state")

    data = resp.json()
    assert data["cycle_running"] is True
    assert data["current_phase"] == "dev_loop"
    assert data["cost_so_far"] == 1.5

    # Cleanup
    state.end_cycle()


async def test_dashboard_history_no_repo(dashboard_app):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.github_repo = ""

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=dashboard_app), base_url="http://test") as client:
        resp = await client.get("/swarm/dashboard/history")

    data = resp.json()
    assert data["history"] == []
    assert "No repo" in data.get("note", "")


async def test_dashboard_history_with_data(dashboard_app):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.github_repo = "owner/repo"

    entries = [{"date": "2026-04-06", "cost_usd": 1.0}]
    with patch("theswarm.cycle_log.read_cycle_history", new_callable=AsyncMock, return_value=entries):
        with patch("theswarm.tools.github.GitHubClient"):
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(transport=ASGITransport(app=dashboard_app), base_url="http://test") as client:
                resp = await client.get("/swarm/dashboard/history")

    data = resp.json()
    assert len(data["history"]) == 1

    # Cleanup
    state.github_repo = ""


async def test_dashboard_history_error(dashboard_app):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.github_repo = "owner/repo"

    with patch("theswarm.tools.github.GitHubClient", side_effect=Exception("fail")):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=dashboard_app), base_url="http://test") as client:
            resp = await client.get("/swarm/dashboard/history")

    data = resp.json()
    assert "error" in data

    # Cleanup
    state.github_repo = ""
