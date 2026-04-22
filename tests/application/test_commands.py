"""Tests for application layer commands."""

from __future__ import annotations

import pytest

from theswarm.application.commands.create_project import (
    CreateProjectCommand,
    CreateProjectHandler,
)
from theswarm.application.commands.delete_project import (
    DeleteProjectCommand,
    DeleteProjectHandler,
)
from theswarm.application.commands.manage_schedule import (
    DeleteScheduleCommand,
    DeleteScheduleHandler,
    DisableScheduleCommand,
    DisableScheduleHandler,
    SetScheduleCommand,
    SetScheduleHandler,
)
from theswarm.application.commands.record_activity import (
    RecordActivityCommand,
    RecordActivityHandler,
)
from theswarm.application.commands.run_cycle import (
    RunCycleCommand,
    RunCycleHandler,
)
from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.events import AgentActivity, CycleStarted
from theswarm.domain.cycles.value_objects import CycleStatus
from theswarm.domain.events import DomainEvent
from theswarm.domain.projects.value_objects import Framework
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


@pytest.fixture()
def event_bus():
    return EventBus()


# ── CreateProject ────────────────────────────────────────────────


class TestCreateProjectCommand:
    async def test_create_project(self, project_repo):
        handler = CreateProjectHandler(project_repo)
        cmd = CreateProjectCommand(
            project_id="my-app",
            repo="owner/my-app",
            framework="fastapi",
            team_channel="dev",
        )
        project = await handler.handle(cmd)

        assert project.id == "my-app"
        assert project.framework == Framework.FASTAPI
        assert project.team_channel == "dev"

        # Persisted
        loaded = await project_repo.get("my-app")
        assert loaded is not None
        assert loaded.id == "my-app"

    async def test_create_project_auto_framework(self, project_repo):
        handler = CreateProjectHandler(project_repo)
        cmd = CreateProjectCommand(project_id="x", repo="o/x")
        project = await handler.handle(cmd)
        assert project.framework == Framework.AUTO

    async def test_create_project_duplicate_raises(self, project_repo):
        handler = CreateProjectHandler(project_repo)
        cmd = CreateProjectCommand(project_id="a", repo="o/a")
        await handler.handle(cmd)

        with pytest.raises(ValueError, match="already exists"):
            await handler.handle(cmd)

    async def test_create_project_with_config(self, project_repo):
        handler = CreateProjectHandler(project_repo)
        cmd = CreateProjectCommand(
            project_id="x", repo="o/x", max_daily_stories=10,
        )
        project = await handler.handle(cmd)
        assert project.config.max_daily_stories == 10

    async def test_create_project_assigns_core_roster_when_service_provided(
        self, project_repo, db,
    ):
        from theswarm.application.services.role_assignment_service import (
            RoleAssignmentService,
        )
        from theswarm.domain.agents.value_objects import CORE_PROJECT_ROLES
        from theswarm.infrastructure.agents.role_assignment_repo import (
            SQLiteRoleAssignmentRepository,
        )

        role_repo = SQLiteRoleAssignmentRepository(db)
        service = RoleAssignmentService(
            role_repo,
            pool=("Mei", "Aarav", "Kenji", "Ines", "Priya", "Oluwa"),
        )
        handler = CreateProjectHandler(project_repo, role_service=service)

        await handler.handle(CreateProjectCommand(project_id="pp", repo="o/pp"))

        roster = await role_repo.list_for_project("pp")
        assert {a.role for a in roster} == set(CORE_PROJECT_ROLES)
        codenames = {a.codename for a in roster}
        assert len(codenames) == 4  # All distinct.

    async def test_create_project_tolerates_roster_failure(
        self, project_repo,
    ):
        class BoomService:
            async def assign_core_roster(self, project_id: str):
                raise RuntimeError("role service down")

        handler = CreateProjectHandler(project_repo, role_service=BoomService())
        # Project creation still succeeds; roster failure is swallowed.
        project = await handler.handle(
            CreateProjectCommand(project_id="r", repo="o/r"),
        )
        assert project.id == "r"
        assert await project_repo.get("r") is not None


# ── DeleteProject ────────────────────────────────────────────────


class TestDeleteProjectCommand:
    async def test_delete_project(self, project_repo):
        create_handler = CreateProjectHandler(project_repo)
        await create_handler.handle(
            CreateProjectCommand(project_id="x", repo="o/x"),
        )

        handler = DeleteProjectHandler(project_repo)
        await handler.handle(DeleteProjectCommand(project_id="x"))

        assert await project_repo.get("x") is None

    async def test_delete_nonexistent_raises(self, project_repo):
        handler = DeleteProjectHandler(project_repo)
        with pytest.raises(ValueError, match="not found"):
            await handler.handle(DeleteProjectCommand(project_id="nope"))


# ── RunCycle ─────────────────────────────────────────────────────


class TestRunCycleCommand:
    async def test_run_cycle(self, project_repo, cycle_repo, event_bus):
        # Setup project
        create_handler = CreateProjectHandler(project_repo)
        await create_handler.handle(
            CreateProjectCommand(project_id="p1", repo="o/p1"),
        )

        received: list[DomainEvent] = []
        event_bus.subscribe(CycleStarted, lambda e: received.append(e))

        handler = RunCycleHandler(project_repo, cycle_repo, event_bus)
        cycle_id = await handler.handle(
            RunCycleCommand(project_id="p1", triggered_by="test"),
        )

        assert cycle_id is not None
        # Cycle persisted and running
        cycle = await cycle_repo.get(cycle_id)
        assert cycle is not None
        assert cycle.status == CycleStatus.RUNNING
        assert cycle.triggered_by == "test"

        # Event emitted
        assert len(received) == 1
        assert received[0].project_id == "p1"

    async def test_run_cycle_unknown_project(self, project_repo, cycle_repo, event_bus):
        handler = RunCycleHandler(project_repo, cycle_repo, event_bus)
        with pytest.raises(ValueError, match="not found"):
            await handler.handle(RunCycleCommand(project_id="nope"))


# ── RecordActivity ───────────────────────────────────────────────


class TestRecordActivityCommand:
    async def test_record_activity(self, event_bus):
        received: list[DomainEvent] = []
        event_bus.subscribe(AgentActivity, lambda e: received.append(e))

        handler = RecordActivityHandler(event_bus)
        await handler.handle(
            RecordActivityCommand(
                cycle_id="c1",
                project_id="p1",
                agent="dev",
                action="implement",
                detail="Working on feature X",
            )
        )

        assert len(received) == 1
        assert received[0].agent == "dev"
        assert received[0].action == "implement"


# ── SetSchedule ──────────────────────────────────────────────────


class TestSetScheduleCommand:
    async def test_set_schedule(self, project_repo, schedule_repo):
        # Create project first
        await CreateProjectHandler(project_repo).handle(
            CreateProjectCommand(project_id="p1", repo="o/p1"),
        )

        handler = SetScheduleHandler(project_repo, schedule_repo)
        schedule = await handler.handle(
            SetScheduleCommand(project_id="p1", cron="0 8 * * 1-5"),
        )

        assert str(schedule.cron) == "0 8 * * 1-5"
        assert schedule.enabled is True

    async def test_set_schedule_unknown_project(self, project_repo, schedule_repo):
        handler = SetScheduleHandler(project_repo, schedule_repo)
        with pytest.raises(ValueError, match="not found"):
            await handler.handle(
                SetScheduleCommand(project_id="nope", cron="0 8 * * *"),
            )

    async def test_update_existing_schedule(self, project_repo, schedule_repo):
        await CreateProjectHandler(project_repo).handle(
            CreateProjectCommand(project_id="p1", repo="o/p1"),
        )

        handler = SetScheduleHandler(project_repo, schedule_repo)
        await handler.handle(
            SetScheduleCommand(project_id="p1", cron="0 8 * * *"),
        )
        updated = await handler.handle(
            SetScheduleCommand(project_id="p1", cron="0 9 * * *"),
        )

        assert str(updated.cron) == "0 9 * * *"
        # Only one schedule exists
        loaded = await schedule_repo.get_by_project("p1")
        assert str(loaded.cron) == "0 9 * * *"

    async def test_invalid_cron_raises(self, project_repo, schedule_repo):
        await CreateProjectHandler(project_repo).handle(
            CreateProjectCommand(project_id="p1", repo="o/p1"),
        )

        handler = SetScheduleHandler(project_repo, schedule_repo)
        with pytest.raises(ValueError, match="Invalid cron"):
            await handler.handle(
                SetScheduleCommand(project_id="p1", cron="bad"),
            )


# ── DisableSchedule ──────────────────────────────────────────────


class TestDisableScheduleCommand:
    async def test_disable(self, project_repo, schedule_repo):
        await CreateProjectHandler(project_repo).handle(
            CreateProjectCommand(project_id="p1", repo="o/p1"),
        )
        await SetScheduleHandler(project_repo, schedule_repo).handle(
            SetScheduleCommand(project_id="p1", cron="0 8 * * *"),
        )

        handler = DisableScheduleHandler(schedule_repo)
        await handler.handle(DisableScheduleCommand(project_id="p1"))

        loaded = await schedule_repo.get_by_project("p1")
        assert loaded.enabled is False

    async def test_disable_nonexistent(self, schedule_repo):
        handler = DisableScheduleHandler(schedule_repo)
        with pytest.raises(ValueError, match="No schedule"):
            await handler.handle(DisableScheduleCommand(project_id="nope"))


# ── DeleteSchedule ───────────────────────────────────────────────


class TestDeleteScheduleCommand:
    async def test_delete(self, project_repo, schedule_repo):
        await CreateProjectHandler(project_repo).handle(
            CreateProjectCommand(project_id="p1", repo="o/p1"),
        )
        await SetScheduleHandler(project_repo, schedule_repo).handle(
            SetScheduleCommand(project_id="p1", cron="0 8 * * *"),
        )

        handler = DeleteScheduleHandler(schedule_repo)
        await handler.handle(DeleteScheduleCommand(project_id="p1"))

        assert await schedule_repo.get_by_project("p1") is None

    async def test_delete_nonexistent(self, schedule_repo):
        handler = DeleteScheduleHandler(schedule_repo)
        with pytest.raises(ValueError, match="No schedule"):
            await handler.handle(DeleteScheduleCommand(project_id="nope"))
