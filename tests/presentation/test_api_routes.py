"""Tests for the agent-consumable JSON API surface in presentation/web/routes/api.py.

Every dashboard feature should be reachable via /api/* so AI agents can drive
the system programmatically without parsing HTML.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus
from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.value_objects import CronExpression
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteActivityRepository,
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    SQLiteScheduleRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture(autouse=True)
def _clear_cycle_tracker():
    """Ensure the module-level CycleTracker singleton doesn't leak between tests."""
    from theswarm.api import get_cycle_tracker
    tracker = get_cycle_tracker()
    tracker._cycles.clear()
    tracker._tasks.clear()
    yield
    tracker._cycles.clear()
    tracker._tasks.clear()


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "api.db"))
    yield conn
    await conn.close()


@pytest.fixture
def project_repo(db):
    return SQLiteProjectRepository(db)


@pytest.fixture
def cycle_repo(db):
    return SQLiteCycleRepository(db)


@pytest.fixture
def report_repo(db):
    return SQLiteReportRepository(db)


@pytest.fixture
def schedule_repo(db):
    return SQLiteScheduleRepository(db)


@pytest.fixture
def activity_repo(db):
    return SQLiteActivityRepository(db)


@pytest.fixture
def app(project_repo, cycle_repo, report_repo, schedule_repo, activity_repo):
    bus = EventBus()
    hub = SSEHub()
    return create_web_app(
        project_repo,
        cycle_repo,
        bus,
        hub,
        report_repo=report_repo,
        schedule_repo=schedule_repo,
        activity_repo=activity_repo,
    )


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_report(rid: str, project: str, day: int) -> DemoReport:
    return DemoReport(
        id=rid,
        cycle_id=CycleId(f"cyc-{rid}"),
        project_id=project,
        created_at=datetime(2026, 4, day, 12, 0, tzinfo=timezone.utc),
        summary=ReportSummary(
            stories_completed=2,
            stories_total=3,
            prs_merged=1,
            tests_passing=10,
            tests_total=12,
            coverage_percent=82.5,
            cost_usd=1.50,
        ),
        stories=(),
        quality_gates=(
            QualityGate(name="tests", status=QualityStatus.PASS, detail="10/12"),
        ),
        agent_learnings=("always run tests",),
        artifacts=(),
    )


# ── Projects CRUD ──────────────────────────────────────────────────


class TestProjectsCrud:
    async def test_create_project(self, client):
        r = await client.post(
            "/api/projects",
            json={"project_id": "svc", "repo": "o/svc", "framework": "fastapi"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["id"] == "svc"
        assert data["repo"] == "o/svc"

    async def test_create_project_missing_fields(self, client):
        r = await client.post("/api/projects", json={"project_id": "svc"})
        assert r.status_code == 422

    async def test_create_project_invalid_json(self, client):
        r = await client.post(
            "/api/projects",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    async def test_create_project_not_dict(self, client):
        r = await client.post("/api/projects", json=["a", "b"])
        assert r.status_code == 422

    async def test_create_duplicate_is_409(self, client, project_repo):
        await project_repo.save(Project(id="dup", repo=RepoUrl("o/dup")))
        r = await client.post(
            "/api/projects", json={"project_id": "dup", "repo": "o/dup"},
        )
        assert r.status_code == 409

    async def test_get_project_detail(self, client, project_repo):
        await project_repo.save(Project(id="p1", repo=RepoUrl("o/p1")))
        r = await client.get("/api/projects/p1")
        assert r.status_code == 200
        assert r.json()["id"] == "p1"

    async def test_get_project_not_found(self, client):
        r = await client.get("/api/projects/nope")
        assert r.status_code == 404

    async def test_delete_project(self, client, project_repo):
        await project_repo.save(Project(id="gone", repo=RepoUrl("o/gone")))
        r = await client.delete("/api/projects/gone")
        assert r.status_code == 204
        follow = await client.get("/api/projects/gone")
        assert follow.status_code == 404

    async def test_delete_missing_project(self, client):
        r = await client.delete("/api/projects/ghost")
        assert r.status_code == 404


# ── Cycles (merged listing + trigger by project_id) ───────────────


class TestCyclesAll:
    async def test_empty_list(self, client):
        r = await client.get("/api/cycles-all")
        assert r.status_code == 200
        data = r.json()
        assert data["cycles"] == []
        assert data["count"] == 0

    async def test_lists_v2_cycles(self, client, cycle_repo):
        now = datetime.now(timezone.utc)
        await cycle_repo.save(
            Cycle(
                id=CycleId("c-a"),
                project_id="p1",
                status=CycleStatus.COMPLETED,
                started_at=now,
                total_cost_usd=0.42,
            ),
        )
        r = await client.get("/api/cycles-all")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 1
        assert any(c["id"] == "c-a" for c in data["cycles"])

    async def test_filters_by_project_id(self, client, cycle_repo):
        now = datetime.now(timezone.utc)
        await cycle_repo.save(
            Cycle(id=CycleId("c-x"), project_id="px", status=CycleStatus.COMPLETED, started_at=now),
        )
        await cycle_repo.save(
            Cycle(id=CycleId("c-y"), project_id="py", status=CycleStatus.COMPLETED, started_at=now),
        )
        r = await client.get("/api/cycles-all?project_id=px")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["cycles"]]
        assert "c-x" in ids and "c-y" not in ids


class TestTriggerCycleForProject:
    async def test_unknown_project_is_404(self, client):
        r = await client.post("/api/projects/unknown/cycle")
        assert r.status_code == 404

    async def test_known_project_returns_202(self, client, project_repo):
        await project_repo.save(Project(id="triggerme", repo=RepoUrl("o/triggerme")))
        with patch("theswarm.api.run_api_cycle", new_callable=AsyncMock):
            r = await client.post(
                "/api/projects/triggerme/cycle",
                json={"description": "do the thing"},
            )
        assert r.status_code == 202
        data = r.json()
        assert data["project_id"] == "triggerme"
        assert data["repo"].endswith("triggerme")
        assert "cycle_id" in data

    async def test_handles_empty_body(self, client, project_repo):
        await project_repo.save(Project(id="nobody", repo=RepoUrl("o/nobody")))
        with patch("theswarm.api.run_api_cycle", new_callable=AsyncMock):
            r = await client.post("/api/projects/nobody/cycle")
        assert r.status_code == 202


# ── Reports ────────────────────────────────────────────────────────


class TestReports:
    async def test_list_reports_empty(self, client):
        r = await client.get("/api/reports")
        assert r.status_code == 200
        assert r.json() == {"reports": [], "count": 0}

    async def test_list_reports_all(self, client, report_repo):
        await report_repo.save(_make_report("r1", "alpha", 1))
        await report_repo.save(_make_report("r2", "beta", 2))
        r = await client.get("/api/reports")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2
        assert {rep["id"] for rep in data["reports"]} == {"r1", "r2"}

    async def test_list_reports_by_project(self, client, report_repo):
        await report_repo.save(_make_report("r1", "alpha", 1))
        await report_repo.save(_make_report("r2", "beta", 2))
        r = await client.get("/api/reports?project_id=alpha")
        data = r.json()
        assert data["count"] == 1
        assert data["reports"][0]["project_id"] == "alpha"

    async def test_get_report_by_id(self, client, report_repo):
        await report_repo.save(_make_report("r-detail", "alpha", 3))
        r = await client.get("/api/reports/id/r-detail")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "r-detail"
        assert data["summary"]["coverage_percent"] == 82.5
        assert "stories" in data
        assert "artifacts" in data
        assert data["agent_learnings"] == ["always run tests"]

    async def test_get_report_by_id_not_found(self, client):
        r = await client.get("/api/reports/id/missing")
        assert r.status_code == 404


# ── Demos ──────────────────────────────────────────────────────────


class TestDemosApi:
    async def test_list_demos_empty(self, client):
        r = await client.get("/api/demos")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0

    async def test_list_demos_groups_by_project(self, client, project_repo, report_repo):
        await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
        await project_repo.save(Project(id="beta", repo=RepoUrl("o/beta")))
        await report_repo.save(_make_report("a1", "alpha", 1))
        await report_repo.save(_make_report("b1", "beta", 1))

        r = await client.get("/api/demos")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        assert "alpha" in data["demos_by_project"]
        assert "beta" in data["demos_by_project"]

    async def test_list_demos_filter_by_project(self, client, project_repo, report_repo):
        await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
        await project_repo.save(Project(id="beta", repo=RepoUrl("o/beta")))
        await report_repo.save(_make_report("a1", "alpha", 1))
        await report_repo.save(_make_report("b1", "beta", 1))

        r = await client.get("/api/demos?project=alpha")
        data = r.json()
        assert "alpha" in data["demos_by_project"]
        assert "beta" not in data["demos_by_project"]

    async def test_list_demos_filter_by_since(self, client, project_repo, report_repo):
        await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
        await report_repo.save(_make_report("old", "alpha", 1))
        await report_repo.save(_make_report("new", "alpha", 20))
        r = await client.get("/api/demos?since=2026-04-10")
        data = r.json()
        ids = [d["id"] for d in data["demos_by_project"]["alpha"]]
        assert "new" in ids and "old" not in ids

    async def test_list_demos_invalid_since(self, client):
        r = await client.get("/api/demos?since=not-a-date")
        assert r.status_code == 422

    async def test_get_demo_by_id(self, client, report_repo):
        await report_repo.save(_make_report("demo-1", "alpha", 5))
        r = await client.get("/api/demos/demo-1")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "demo-1"
        assert "stories" in data

    async def test_get_demo_not_found(self, client):
        r = await client.get("/api/demos/nope")
        assert r.status_code == 404


# ── Schedules CRUD ────────────────────────────────────────────────


class TestSchedules:
    async def test_list_empty(self, client):
        r = await client.get("/api/schedules")
        assert r.status_code == 200
        assert r.json() == {"schedules": [], "count": 0}

    async def test_get_missing_returns_404(self, client):
        r = await client.get("/api/schedules/none")
        assert r.status_code == 404

    async def test_set_requires_known_project(self, client):
        r = await client.put("/api/schedules/ghost", json={"cron": "0 8 * * 1-5"})
        assert r.status_code == 404

    async def test_set_and_get_schedule(self, client, project_repo):
        await project_repo.save(Project(id="sched", repo=RepoUrl("o/sched")))
        r = await client.put(
            "/api/schedules/sched",
            json={"cron": "0 8 * * 1-5"},
        )
        assert r.status_code == 200
        assert r.json()["cron"] == "0 8 * * 1-5"

        follow = await client.get("/api/schedules/sched")
        assert follow.status_code == 200
        assert follow.json()["project_id"] == "sched"
        assert follow.json()["enabled"] is True

    async def test_set_schedule_invalid_body(self, client, project_repo):
        await project_repo.save(Project(id="sched2", repo=RepoUrl("o/sched2")))
        r = await client.put("/api/schedules/sched2", json={})
        assert r.status_code == 422

    async def test_set_schedule_bad_json(self, client):
        r = await client.put(
            "/api/schedules/sched3",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    async def test_list_after_create(self, client, project_repo):
        await project_repo.save(Project(id="sched4", repo=RepoUrl("o/sched4")))
        await client.put("/api/schedules/sched4", json={"cron": "0 * * * *"})
        r = await client.get("/api/schedules")
        data = r.json()
        assert data["count"] == 1
        assert data["schedules"][0]["project_id"] == "sched4"

    async def test_delete_schedule(self, client, project_repo, schedule_repo):
        await project_repo.save(Project(id="sched5", repo=RepoUrl("o/sched5")))
        await schedule_repo.save(
            Schedule(
                project_id="sched5",
                cron=CronExpression("0 9 * * *"),
                enabled=True,
            ),
        )
        r = await client.delete("/api/schedules/sched5")
        assert r.status_code == 204

    async def test_delete_missing_schedule(self, client):
        r = await client.delete("/api/schedules/missing")
        assert r.status_code == 404


# ── Activities ─────────────────────────────────────────────────────


class TestActivities:
    async def test_empty_activity_feed(self, client):
        r = await client.get("/api/activities")
        assert r.status_code == 200
        data = r.json()
        assert data["activities"] == []
        assert data["count"] == 0

    async def test_reads_saved_activities(self, client, activity_repo):
        await activity_repo.save(
            cycle_id="c1", project_id="p1", agent="dev",
            action="commit", detail="did stuff",
        )
        r = await client.get("/api/activities")
        data = r.json()
        assert data["count"] == 1
        assert data["activities"][0]["agent"] == "dev"

    async def test_filters_by_project(self, client, activity_repo):
        await activity_repo.save(
            cycle_id="c1", project_id="p1", agent="dev", action="a", detail="",
        )
        await activity_repo.save(
            cycle_id="c2", project_id="p2", agent="dev", action="b", detail="",
        )
        r = await client.get("/api/activities?project_id=p1")
        data = r.json()
        assert data["count"] == 1
        assert data["activities"][0]["project_id"] == "p1"
