"""Tests for presentation/web/app.py — full HTTP integration tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import Framework, RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

from datetime import datetime, timezone


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def repos(db):
    return SQLiteProjectRepository(db), SQLiteCycleRepository(db)


@pytest.fixture()
def app(repos):
    project_repo, cycle_repo = repos
    bus = EventBus()
    hub = SSEHub()
    return create_web_app(project_repo, cycle_repo, bus, hub)


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Dashboard ────────────────────────────────────────────────────


class TestDashboardRoutes:
    async def test_dashboard_empty(self, client):
        r = await client.get("/")
        assert r.status_code == 200
        assert "TheSwarm" in r.text
        assert "No active cycles" in r.text

    async def test_dashboard_with_project(self, repos, client):
        project_repo, cycle_repo = repos
        await project_repo.save(Project(id="p1", repo=RepoUrl("o/p1")))

        r = await client.get("/")
        assert r.status_code == 200
        assert "p1" in r.text


# ── Projects ─────────────────────────────────────────────────────


class TestProjectRoutes:
    async def test_list_empty(self, client):
        r = await client.get("/projects/")
        assert r.status_code == 200
        assert "No projects" in r.text

    async def test_create_form(self, client):
        r = await client.get("/projects/new")
        assert r.status_code == 200
        assert "Add Project" in r.text

    async def test_create_and_list(self, client):
        r = await client.post(
            "/projects/",
            data={
                "project_id": "my-app",
                "repo": "owner/my-app",
                "framework": "fastapi",
                "ticket_source": "github",
                "team_channel": "",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "my-app" in r.text

    async def test_project_detail(self, repos, client):
        project_repo, _ = repos
        await project_repo.save(
            Project(id="x", repo=RepoUrl("o/x"), framework=Framework.DJANGO),
        )

        r = await client.get("/projects/x")
        assert r.status_code == 200
        assert "django" in r.text

    async def test_project_not_found(self, client):
        r = await client.get("/projects/nope")
        assert r.status_code == 404

    async def test_delete_project(self, repos, client):
        project_repo, _ = repos
        await project_repo.save(Project(id="del-me", repo=RepoUrl("o/del-me")))

        r = await client.post("/projects/del-me/delete", follow_redirects=True)
        assert r.status_code == 200
        assert "del-me" not in r.text


# ── Cycles ───────────────────────────────────────────────────────


class TestCycleRoutes:
    async def test_list_empty(self, client):
        r = await client.get("/cycles/")
        assert r.status_code == 200
        assert "No cycles" in r.text

    async def test_cycle_detail(self, repos, client):
        _, cycle_repo = repos
        now = datetime.now(timezone.utc)
        await cycle_repo.save(
            Cycle(
                id=CycleId("test-cycle-123"),
                project_id="p1",
                status=CycleStatus.RUNNING,
                started_at=now,
                total_cost_usd=0.25,
            ),
        )

        r = await client.get("/cycles/test-cycle-123")
        assert r.status_code == 200
        assert "running" in r.text

    async def test_cycle_not_found(self, client):
        r = await client.get("/cycles/nope")
        assert r.status_code == 404

    async def test_trigger_cycle(self, repos, client):
        project_repo, _ = repos
        await project_repo.save(Project(id="p1", repo=RepoUrl("o/p1")))

        r = await client.post(
            "/cycles/trigger",
            data={"project_id": "p1"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "running" in r.text.lower() or "pending" in r.text.lower()


# ── Health ───────────────────────────────────────────────────────


class TestHealthRoutes:
    async def test_health_ok(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert data["checks"]["database"] == "connected"


# ── API ──────────────────────────────────────────────────────────


class TestAPIRoutes:
    async def test_api_projects_empty(self, client):
        r = await client.get("/api/projects")
        assert r.status_code == 200
        assert r.json() == []

    async def test_api_projects_with_data(self, repos, client):
        project_repo, _ = repos
        await project_repo.save(Project(id="a", repo=RepoUrl("o/a")))

        r = await client.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["id"] == "a"

    async def test_api_dashboard(self, client):
        r = await client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert data["active_cycles"] == 0
        assert data["total_cost_today"] == 0.0

    async def test_api_cycle_not_found(self, client):
        r = await client.get("/api/cycles/nope")
        assert r.status_code == 404

    async def test_api_cycle_found(self, repos, client):
        _, cycle_repo = repos
        now = datetime.now(timezone.utc)
        await cycle_repo.save(
            Cycle(
                id=CycleId("c1"),
                project_id="p1",
                status=CycleStatus.COMPLETED,
                started_at=now,
                total_cost_usd=1.23,
            ),
        )

        r = await client.get("/api/cycles/c1")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "completed"
        assert data["total_cost_usd"] == pytest.approx(1.23)

    async def test_api_sse_endpoint_exists(self, app):
        """SSE endpoint is registered and the hub is wired."""
        # Verify the route exists
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/api/events" in routes
        # Verify SSE hub is on app state
        assert hasattr(app.state, "sse_hub")
