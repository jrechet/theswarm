"""Tests for application layer queries."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.get_project import GetProjectQuery
from theswarm.application.queries.get_schedule import (
    GetScheduleQuery,
    ListEnabledSchedulesQuery,
)
from theswarm.application.queries.list_cycles import ListCyclesQuery
from theswarm.application.queries.list_projects import ListProjectsQuery
from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus, PhaseStatus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import Framework, RepoUrl
from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.value_objects import CronExpression
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    SQLiteScheduleRepository,
    init_db,
)


@pytest.fixture()
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)
    yield conn
    await conn.close()


@pytest.fixture()
def project_repo(db):
    return SQLiteProjectRepository(db)


@pytest.fixture()
def cycle_repo(db):
    return SQLiteCycleRepository(db)


@pytest.fixture()
def schedule_repo(db):
    return SQLiteScheduleRepository(db)


# ── ListProjects ─────────────────────────────────────────────────


class TestListProjectsQuery:
    async def test_empty(self, project_repo):
        q = ListProjectsQuery(project_repo)
        result = await q.execute()
        assert result == []

    async def test_returns_dtos(self, project_repo):
        await project_repo.save(
            Project(id="a", repo=RepoUrl("o/a"), framework=Framework.FASTAPI),
        )
        await project_repo.save(
            Project(id="b", repo=RepoUrl("o/b")),
        )

        q = ListProjectsQuery(project_repo)
        result = await q.execute()
        assert len(result) == 2
        assert result[0].id == "a"
        assert result[0].framework == "fastapi"
        assert result[1].id == "b"


# ── GetProject ───────────────────────────────────────────────────


class TestGetProjectQuery:
    async def test_found(self, project_repo):
        await project_repo.save(
            Project(id="x", repo=RepoUrl("o/x"), framework=Framework.DJANGO),
        )

        q = GetProjectQuery(project_repo)
        dto = await q.execute("x")
        assert dto is not None
        assert dto.id == "x"
        assert dto.framework == "django"
        assert dto.repo == "o/x"

    async def test_not_found(self, project_repo):
        q = GetProjectQuery(project_repo)
        assert await q.execute("nope") is None


# ── GetCycleStatus ───────────────────────────────────────────────


class TestGetCycleStatusQuery:
    async def test_found(self, cycle_repo):
        now = datetime.now(timezone.utc)
        phase = PhaseExecution(
            phase="morning", agent="po", started_at=now,
            status=PhaseStatus.COMPLETED, completed_at=now,
            tokens_used=1000, cost_usd=0.05, summary="Done",
        )
        cycle = Cycle(
            id=CycleId("c1"), project_id="p1",
            status=CycleStatus.RUNNING, triggered_by="test",
            started_at=now, phases=(phase,),
            total_cost_usd=0.05,
        )
        await cycle_repo.save(cycle)

        q = GetCycleStatusQuery(cycle_repo)
        dto = await q.execute("c1")
        assert dto is not None
        assert dto.status == "running"
        assert dto.triggered_by == "test"
        assert len(dto.phases) == 1
        assert dto.phases[0].agent == "po"
        assert dto.total_cost_usd == pytest.approx(0.05)

    async def test_not_found(self, cycle_repo):
        q = GetCycleStatusQuery(cycle_repo)
        assert await q.execute("nope") is None


# ── ListCycles ───────────────────────────────────────────────────


class TestListCyclesQuery:
    async def test_returns_cycles(self, cycle_repo):
        now = datetime.now(timezone.utc)
        for i in range(3):
            await cycle_repo.save(
                Cycle(id=CycleId(f"c{i}"), project_id="p1", started_at=now),
            )

        q = ListCyclesQuery(cycle_repo)
        result = await q.execute("p1")
        assert len(result) == 3

    async def test_respects_limit(self, cycle_repo):
        now = datetime.now(timezone.utc)
        for i in range(10):
            await cycle_repo.save(
                Cycle(id=CycleId(f"c{i}"), project_id="p1", started_at=now),
            )

        q = ListCyclesQuery(cycle_repo)
        result = await q.execute("p1", limit=3)
        assert len(result) == 3

    async def test_empty(self, cycle_repo):
        q = ListCyclesQuery(cycle_repo)
        assert await q.execute("nope") == []


# ── GetDashboard ─────────────────────────────────────────────────


class TestGetDashboardQuery:
    async def test_empty_dashboard(self, project_repo, cycle_repo):
        q = GetDashboardQuery(project_repo, cycle_repo)
        dto = await q.execute()
        assert dto.projects == []
        assert dto.active_cycles == []
        assert dto.total_cost_today == 0.0

    async def test_with_projects_and_cycles(self, project_repo, cycle_repo):
        await project_repo.save(Project(id="p1", repo=RepoUrl("o/p1")))

        now = datetime.now(timezone.utc)
        await cycle_repo.save(
            Cycle(
                id=CycleId("c1"), project_id="p1",
                status=CycleStatus.RUNNING, started_at=now,
                total_cost_usd=0.50,
            ),
        )
        await cycle_repo.save(
            Cycle(
                id=CycleId("c2"), project_id="p1",
                status=CycleStatus.COMPLETED, started_at=now,
                total_cost_usd=1.00,
            ),
        )

        q = GetDashboardQuery(project_repo, cycle_repo)
        dto = await q.execute()

        assert len(dto.projects) == 1
        assert len(dto.active_cycles) == 1
        assert dto.active_cycles[0].status == "running"
        assert dto.total_cost_today == pytest.approx(1.50)

    async def test_cost_and_cycles_per_day_7d(self, project_repo, cycle_repo):
        from datetime import timedelta
        await project_repo.save(Project(id="p1", repo=RepoUrl("o/p1")))

        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)
        await cycle_repo.save(
            Cycle(
                id=CycleId("c-today"), project_id="p1",
                status=CycleStatus.COMPLETED, started_at=now,
                total_cost_usd=0.50,
            ),
        )
        await cycle_repo.save(
            Cycle(
                id=CycleId("c-twodays"), project_id="p1",
                status=CycleStatus.COMPLETED, started_at=two_days_ago,
                total_cost_usd=1.00,
            ),
        )

        q = GetDashboardQuery(project_repo, cycle_repo)
        dto = await q.execute()

        assert len(dto.cost_per_day_7d) == 7
        assert len(dto.cycles_per_day_7d) == 7
        # index 6 = today, index 4 = 2 days ago
        assert dto.cost_per_day_7d[6] == pytest.approx(0.50)
        assert dto.cost_per_day_7d[4] == pytest.approx(1.00)
        assert dto.cycles_per_day_7d[6] == 1
        assert dto.cycles_per_day_7d[4] == 1


# ── GetSchedule ──────────────────────────────────────────────────


class TestGetScheduleQuery:
    async def test_found(self, schedule_repo):
        await schedule_repo.save(
            Schedule(project_id="p1", cron=CronExpression("0 8 * * 1-5")),
        )

        q = GetScheduleQuery(schedule_repo)
        dto = await q.execute("p1")
        assert dto is not None
        assert dto.cron == "0 8 * * 1-5"
        assert dto.enabled is True

    async def test_not_found(self, schedule_repo):
        q = GetScheduleQuery(schedule_repo)
        assert await q.execute("nope") is None


class TestListEnabledSchedulesQuery:
    async def test_lists_enabled_only(self, schedule_repo):
        await schedule_repo.save(
            Schedule(project_id="p1", cron=CronExpression("0 8 * * *")),
        )
        await schedule_repo.save(
            Schedule(project_id="p2", cron=CronExpression("0 9 * * *"), enabled=False),
        )

        q = ListEnabledSchedulesQuery(schedule_repo)
        result = await q.execute()
        assert len(result) == 1
        assert result[0].project_id == "p1"
