"""Integration tests: unified server creates a single web app with all routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app


@pytest.fixture
async def app(tmp_path):
    """Create a v2 web app with injected repos."""
    conn = await init_db(str(tmp_path / "test.db"))
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()
    web_app = create_web_app(project_repo, cycle_repo, bus)
    yield web_app
    await conn.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestDashboardRoutes:
    """Dashboard and core routes work."""

    async def test_dashboard_home(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200

    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_projects_list(self, client):
        resp = await client.get("/projects", follow_redirects=True)
        assert resp.status_code == 200


class TestAPIRoutes:
    """API routes work."""

    async def test_api_projects(self, client):
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_api_dashboard(self, client):
        resp = await client.get("/api/dashboard")
        assert resp.status_code == 200

    async def test_api_live_state(self, client):
        resp = await client.get("/api/live/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "cycle_running" in data

    async def test_api_cycles_list(self, client):
        resp = await client.get("/api/cycles")
        assert resp.status_code == 200
        assert "cycles" in resp.json()

    async def test_api_live_history_no_repo(self, client):
        resp = await client.get("/api/live/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["history"] == []


class TestAllRoutesCoexist:
    """Dashboard, API, and live routes all work together."""

    async def test_dashboard_and_api(self, client):
        health = await client.get("/health")
        projects = await client.get("/api/projects")
        live = await client.get("/api/live/state")
        assert health.status_code == 200
        assert projects.status_code == 200
        assert live.status_code == 200
