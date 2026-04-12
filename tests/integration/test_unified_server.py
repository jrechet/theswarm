"""Integration tests: unified server creates a web app with both v2 and legacy routes."""

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

    # Mount legacy routes (same as server.py does)
    from theswarm.dashboard import register_dashboard_routes
    from theswarm.api import register_api_routes
    register_dashboard_routes(web_app)
    register_api_routes(web_app, allowed_repos=[])

    yield web_app
    await conn.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestV2Routes:
    """v2 Clean Architecture routes work."""

    async def test_dashboard_home(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200

    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_projects_list(self, client):
        resp = await client.get("/projects", follow_redirects=True)
        assert resp.status_code == 200


class TestLegacyRoutes:
    """Old dashboard and API routes mounted alongside v2."""

    async def test_legacy_dashboard(self, client):
        resp = await client.get("/swarm/dashboard")
        assert resp.status_code == 200
        assert "TheSwarm Dashboard" in resp.text

    async def test_legacy_dashboard_state(self, client):
        resp = await client.get("/swarm/dashboard/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "cycle_running" in data

    async def test_legacy_api_cycles(self, client):
        resp = await client.get("/api/cycles")
        assert resp.status_code == 200
        data = resp.json()
        assert "cycles" in data


class TestBothCoexist:
    """v2 and legacy routes can coexist without conflicts."""

    async def test_v2_health_and_legacy_dashboard(self, client):
        health = await client.get("/health")
        dashboard = await client.get("/swarm/dashboard")
        assert health.status_code == 200
        assert dashboard.status_code == 200

    async def test_v2_projects_and_legacy_api(self, client):
        projects = await client.get("/projects", follow_redirects=True)
        api_cycles = await client.get("/api/cycles")
        assert projects.status_code == 200
        assert api_cycles.status_code == 200
