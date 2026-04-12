"""Tests for live cycle state API endpoints (migrated from legacy dashboard)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app


@pytest.fixture()
async def app(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()
    web_app = create_web_app(project_repo, cycle_repo, bus)
    yield web_app
    await conn.close()


@pytest.fixture()
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_live_state_idle(client):
    resp = await client.get("/api/live/state")
    data = resp.json()
    assert data["cycle_running"] is False
    assert data["cost_so_far"] == 0.0


async def test_live_state_running(client):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.start_cycle("owner/repo")
    state.current_phase = "dev_loop"
    state.cost_so_far = 1.5

    resp = await client.get("/api/live/state")
    data = resp.json()
    assert data["cycle_running"] is True
    assert data["current_phase"] == "dev_loop"
    assert data["cost_so_far"] == 1.5

    state.end_cycle()


async def test_live_history_no_repo(client):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.github_repo = ""

    resp = await client.get("/api/live/history")
    data = resp.json()
    assert data["history"] == []
    assert "No repo" in data.get("note", "")


async def test_live_history_with_data(client):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.github_repo = "owner/repo"

    entries = [{"date": "2026-04-06", "cost_usd": 1.0}]
    with patch("theswarm.cycle_log.read_cycle_history", new_callable=AsyncMock, return_value=entries):
        with patch("theswarm.tools.github.GitHubClient"):
            resp = await client.get("/api/live/history")

    data = resp.json()
    assert len(data["history"]) == 1

    state.github_repo = ""


async def test_live_history_error(client):
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.github_repo = "owner/repo"

    with patch("theswarm.tools.github.GitHubClient", side_effect=Exception("fail")):
        resp = await client.get("/api/live/history")

    data = resp.json()
    assert "error" in data

    state.github_repo = ""
