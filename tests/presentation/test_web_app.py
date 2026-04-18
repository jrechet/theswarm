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

    async def test_dashboard_renders_sparklines(self, repos, client):
        from theswarm.domain.cycles.entities import Cycle

        project_repo, cycle_repo = repos
        await project_repo.save(Project(id="p1", repo=RepoUrl("o/p1")))
        now = datetime.now(timezone.utc)
        await cycle_repo.save(
            Cycle(
                id=CycleId("sparkline-1"),
                project_id="p1",
                status=CycleStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                total_cost_usd=0.42,
            ),
        )

        r = await client.get("/")
        assert r.status_code == 200
        assert r.text.count('class="sparkline"') >= 1 or 'class="sparkline sparkline-empty"' in r.text


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

    async def test_project_detail_has_demos_link(self, repos, client):
        project_repo, _ = repos
        await project_repo.save(Project(id="with-demos", repo=RepoUrl("o/with-demos")))

        r = await client.get("/projects/with-demos")
        assert r.status_code == 200
        assert "/demos/?project=with-demos" in r.text
        assert 'data-testid="project-demos-link"' in r.text


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

    async def test_cycle_timeline_shows_duration(self, repos, client):
        from datetime import timedelta
        from theswarm.domain.cycles.entities import Cycle, PhaseExecution
        from theswarm.domain.cycles.value_objects import PhaseStatus

        _, cycle_repo = repos
        started = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
        phase = PhaseExecution(
            phase="morning",
            agent="po",
            started_at=started,
            completed_at=started + timedelta(seconds=90),
            status=PhaseStatus.COMPLETED,
            tokens_used=1234,
            cost_usd=0.05,
            summary="Selected 3 stories",
        )
        cycle = Cycle(
            id=CycleId("timeline-abc"),
            project_id="p1",
            status=CycleStatus.COMPLETED,
            started_at=started,
            completed_at=started + timedelta(seconds=120),
            phases=(phase,),
        )
        await cycle_repo.save(cycle)

        r = await client.get("/cycles/timeline-abc")
        assert r.status_code == 200
        assert 'data-testid="cycle-timeline"' in r.text
        assert "timeline-bar-fill" in r.text
        assert "1.5" in r.text  # 90 seconds → 1.5 min
        assert "10:00:00" in r.text  # phase start time


# ── Health ───────────────────────────────────────────────────────


class TestHealthRoutes:
    async def test_health_ok(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "uptime_seconds" in data
        assert data["checks"]["database"] == "connected"

    async def test_health_warn_when_bridge_missing_integrations(self, app, client):
        class _Bridge:
            _swarm_po_github = None
            _swarm_po_chat = None
            _swarm_po_vcs_map: dict = {}

        app.state.gateway_bridge = _Bridge()
        try:
            r = await client.get("/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "warn"
            assert data["checks"]["github"] == "missing"
            assert data["checks"]["chat"] == "missing"
        finally:
            del app.state.gateway_bridge

    async def test_health_error_when_db_fails(self, app, client):
        class _BrokenRepo:
            async def list_all(self):
                raise RuntimeError("db down")

        original = app.state.project_repo
        app.state.project_repo = _BrokenRepo()
        try:
            r = await client.get("/health")
            assert r.status_code == 503
            data = r.json()
            assert data["status"] == "error"
            assert data["checks"]["database"] == "error"
        finally:
            app.state.project_repo = original

    async def test_health_derive_status_tri_state(self):
        from theswarm.presentation.web.routes.health import _derive_status

        assert _derive_status({"db": "connected", "sse": "ok"}) == "ok"
        assert _derive_status({"db": "connected", "github": "missing"}) == "warn"
        assert _derive_status({"db": "error", "github": "missing"}) == "error"


class TestMetricsRoute:
    async def test_metrics_exposes_prometheus_format(self, client):
        r = await client.get("/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        body = r.text
        assert "# TYPE theswarm_uptime_seconds gauge" in body
        assert "theswarm_projects_total" in body
        assert 'theswarm_cycles{status="running"}' in body
        assert "theswarm_cycle_cost_usd_sum" in body
        assert "theswarm_cycle_tokens_sum" in body

    async def test_metrics_counts_projects_and_cycles(self, repos, client):
        project_repo, cycle_repo = repos
        await project_repo.save(Project(id="m1", repo=RepoUrl("o/m1")))
        await project_repo.save(Project(id="m2", repo=RepoUrl("o/m2")))

        now = datetime.now(timezone.utc)
        from theswarm.domain.cycles.entities import Cycle
        await cycle_repo.save(
            Cycle(
                id=CycleId("running-1"),
                project_id="m1",
                status=CycleStatus.RUNNING,
                started_at=now,
                total_cost_usd=1.25,
            ),
        )
        await cycle_repo.save(
            Cycle(
                id=CycleId("done-1"),
                project_id="m1",
                status=CycleStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                total_cost_usd=0.75,
            ),
        )

        r = await client.get("/metrics")
        body = r.text
        assert "theswarm_projects_total 2" in body
        assert 'theswarm_cycles{status="running"} 1' in body
        assert 'theswarm_cycles{status="completed"} 1' in body
        assert "theswarm_cycle_cost_usd_sum 2.0000" in body


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
        assert data["active_cycles"] == []
        assert data["recent_cycles"] == []
        assert data["recent_activities"] == []
        assert data["projects"] == []
        assert data["total_cost_today"] == 0.0
        assert data["total_cost_week"] == 0.0
        assert data["success_rate_7d"] == 0.0
        assert data["cycles_completed_7d"] == 0
        assert data["cycles_failed_7d"] == 0
        assert data["counts"] == {"active_cycles": 0, "projects": 0}

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
