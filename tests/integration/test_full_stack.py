"""Cross-layer integration tests: domain → application → infrastructure → presentation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.application.commands.create_project import (
    CreateProjectCommand,
    CreateProjectHandler,
)
from theswarm.application.commands.manage_schedule import (
    SetScheduleCommand,
    SetScheduleHandler,
)
from theswarm.application.commands.run_cycle import RunCycleCommand, RunCycleHandler
from theswarm.application.events.bus import EventBus
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.get_schedule import ListEnabledSchedulesQuery
from theswarm.application.queries.list_projects import ListProjectsQuery
from theswarm.application.services.improvement_engine import ImprovementEngine
from theswarm.application.services.report_generator import ReportGenerator
from theswarm.application.services.startup_validator import StartupValidator
from theswarm.domain.cycles.value_objects import CycleStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    SQLiteScheduleRepository,
    init_db,
)
from theswarm.infrastructure.recording.artifact_store import LocalArtifactStore
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.infrastructure.scheduling.webhook_handler import WebhookHandler


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "integration.db"))
    yield conn
    await conn.close()


@pytest.fixture
def project_repo(db):
    return SQLiteProjectRepository(db)


@pytest.fixture
def cycle_repo(db):
    return SQLiteCycleRepository(db)


@pytest.fixture
def schedule_repo(db):
    return SQLiteScheduleRepository(db)


@pytest.fixture
async def report_repo(tmp_path):
    conn = await init_db(str(tmp_path / "reports.db"))
    yield SQLiteReportRepository(conn)
    await conn.close()


@pytest.fixture
def bus():
    return EventBus()


class TestProjectCycleFlow:
    """End-to-end: create project → run cycle → check dashboard."""

    async def test_full_flow(self, project_repo, cycle_repo, bus):
        # Create project
        create = CreateProjectHandler(project_repo)
        project = await create.handle(
            CreateProjectCommand(project_id="webapp", repo="acme/webapp")
        )
        assert project.id == "webapp"

        # Verify project appears in list
        projects = await ListProjectsQuery(project_repo).execute()
        assert len(projects) == 1

        # Run cycle
        run = RunCycleHandler(project_repo, cycle_repo, bus)
        cycle_id = await run.handle(
            RunCycleCommand(project_id="webapp", triggered_by="integration-test")
        )
        assert cycle_id is not None

        # Dashboard shows the cycle
        dashboard = await GetDashboardQuery(project_repo, cycle_repo).execute()
        assert len(dashboard.projects) == 1
        assert dashboard.projects[0].id == "webapp"

    async def test_cycle_for_nonexistent_project(self, project_repo, cycle_repo, bus):
        run = RunCycleHandler(project_repo, cycle_repo, bus)
        with pytest.raises(ValueError, match="not found"):
            await run.handle(RunCycleCommand(project_id="ghost", triggered_by="test"))


class TestScheduleFlow:
    """Create project → set schedule → list schedules."""

    async def test_schedule_lifecycle(self, project_repo, schedule_repo):
        # Create project first
        create = CreateProjectHandler(project_repo)
        await create.handle(CreateProjectCommand(project_id="api", repo="acme/api"))

        # Set schedule
        set_handler = SetScheduleHandler(project_repo, schedule_repo)
        schedule = await set_handler.handle(
            SetScheduleCommand(project_id="api", cron="0 8 * * 1-5")
        )
        assert str(schedule.cron) == "0 8 * * 1-5"

        # List enabled
        query = ListEnabledSchedulesQuery(schedule_repo)
        schedules = await query.execute()
        assert len(schedules) == 1
        assert schedules[0].project_id == "api"


class TestReportFlow:
    """Generate report → save → retrieve → analyze."""

    async def test_report_lifecycle(self, project_repo, cycle_repo, report_repo, bus):
        # Setup
        create = CreateProjectHandler(project_repo)
        await create.handle(CreateProjectCommand(project_id="app", repo="acme/app"))

        run = RunCycleHandler(project_repo, cycle_repo, bus)
        cycle_id = await run.handle(
            RunCycleCommand(project_id="app", triggered_by="test")
        )

        # Get cycle and generate report
        cycle = await cycle_repo.get(str(cycle_id))
        assert cycle is not None

        generator = ReportGenerator()
        report = generator.generate(cycle)
        assert report.project_id == "app"

        # Save and retrieve
        await report_repo.save(report)
        loaded = await report_repo.get(report.id)
        assert loaded is not None
        assert loaded.project_id == "app"

        # Analyze with improvement engine
        engine = ImprovementEngine()
        suggestions = engine.analyze_report(loaded)
        retro = engine.generate_retrospective(loaded, suggestions)
        assert retro.project_id == "app"


class TestArtifactFlow:
    """Save artifacts → list by cycle."""

    async def test_artifact_storage(self, tmp_path):
        from theswarm.domain.cycles.value_objects import CycleId
        from theswarm.domain.reporting.value_objects import Artifact, ArtifactType

        store = LocalArtifactStore(base_dir=str(tmp_path / "artifacts"))
        cycle_id = CycleId("test-cycle")

        # Save artifacts
        screenshot = Artifact(type=ArtifactType.SCREENSHOT, label="homepage", path="")
        video = Artifact(type=ArtifactType.VIDEO, label="demo", path="")

        path1 = await store.save(cycle_id, screenshot, b"PNG_DATA")
        path2 = await store.save(cycle_id, video, b"WEBM_DATA")

        # List
        artifacts = await store.list_by_cycle(cycle_id)
        assert len(artifacts) == 2

        # URL resolution
        url = await store.get_url(path1)
        assert "homepage" in url


class TestEventBusIntegration:
    """Events flow from commands through the bus to subscribers."""

    async def test_cycle_event_published(self, project_repo, cycle_repo, bus):
        events = []
        bus.subscribe_all(lambda e: events.append(e))

        create = CreateProjectHandler(project_repo)
        await create.handle(CreateProjectCommand(project_id="ev", repo="acme/ev"))

        run = RunCycleHandler(project_repo, cycle_repo, bus)
        await run.handle(RunCycleCommand(project_id="ev", triggered_by="test"))

        assert len(events) >= 1
        assert events[0].__class__.__name__ == "CycleStarted"


class TestWebhookIntegration:
    """Webhook parsing and trigger decision."""

    def test_push_triggers_for_known_repo(self):
        handler = WebhookHandler()
        event = handler.parse_event("push", {
            "ref": "refs/heads/main",
            "repository": {"full_name": "acme/webapp"},
            "sender": {"login": "bot"},
        })
        assert handler.should_trigger_cycle(event, ["acme/webapp"])

    def test_push_ignores_unknown_repo(self):
        handler = WebhookHandler()
        event = handler.parse_event("push", {
            "ref": "refs/heads/main",
            "repository": {"full_name": "other/repo"},
            "sender": {"login": "bot"},
        })
        assert not handler.should_trigger_cycle(event, ["acme/webapp"])


class TestStartupValidation:
    """Validator catches misconfig."""

    def test_valid_config(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "mm-test")
        result = StartupValidator().validate()
        assert result.ok

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = StartupValidator().validate()
        assert not result.ok
