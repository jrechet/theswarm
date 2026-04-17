"""Tests for /demos/ filtering by project and since-date."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.reporting.entities import (
    DemoReport,
    ReportSummary,
    StoryReport,
)
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "demos.db"))
    yield conn
    await conn.close()


@pytest.fixture
async def seeded(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    report_repo = SQLiteReportRepository(db)

    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
    await project_repo.save(Project(id="beta", repo=RepoUrl("o/beta")))

    def _report(rid: str, project: str, day: int) -> DemoReport:
        return DemoReport(
            id=rid,
            cycle_id=CycleId(f"cyc-{rid}"),
            project_id=project,
            created_at=datetime(2026, 4, day, 12, 0, tzinfo=timezone.utc),
            summary=ReportSummary(stories_completed=1, stories_total=1),
            stories=(),
            quality_gates=(),
            agent_learnings=(),
            artifacts=(),
        )

    await report_repo.save(_report("alpha-old", "alpha", 1))
    await report_repo.save(_report("alpha-new", "alpha", 15))
    await report_repo.save(_report("beta-new", "beta", 15))

    return project_repo, cycle_repo, report_repo


@pytest.fixture
def app(seeded):
    project_repo, cycle_repo, report_repo = seeded
    bus = EventBus()
    hub = SSEHub()
    return create_web_app(project_repo, cycle_repo, bus, hub, report_repo=report_repo)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestDemosFilter:
    async def test_no_filter_shows_all(self, client):
        r = await client.get("/demos/")
        assert r.status_code == 200
        assert "cyc-alpha-old" in r.text
        assert "cyc-alpha-new" in r.text
        assert "cyc-beta-new" in r.text

    async def test_filter_by_project_narrows_results(self, client):
        r = await client.get("/demos/?project=alpha")
        assert r.status_code == 200
        assert "cyc-alpha-old" in r.text
        assert "cyc-alpha-new" in r.text
        assert "cyc-beta-new" not in r.text

    async def test_filter_by_since_excludes_older(self, client):
        r = await client.get("/demos/?since=2026-04-10")
        assert r.status_code == 200
        assert "cyc-alpha-old" not in r.text
        assert "cyc-alpha-new" in r.text
        assert "cyc-beta-new" in r.text

    async def test_filter_combining_project_and_since(self, client):
        r = await client.get("/demos/?project=alpha&since=2026-04-10")
        assert r.status_code == 200
        assert "cyc-alpha-new" in r.text
        assert "cyc-alpha-old" not in r.text
        assert "cyc-beta-new" not in r.text

    async def test_invalid_since_falls_back_to_no_date_filter(self, client):
        r = await client.get("/demos/?since=not-a-date")
        assert r.status_code == 200
        assert "cyc-alpha-old" in r.text

    async def test_filter_form_preserves_active_values(self, client):
        r = await client.get("/demos/?project=alpha&since=2026-04-10")
        assert 'value="2026-04-10"' in r.text
        assert 'selected' in r.text


class TestDemoThumbnails:
    def test_thumbnail_path_prefers_top_level_screenshot(self):
        report = DemoReport(
            id="r1",
            cycle_id=CycleId("cyc-r1"),
            project_id="p",
            artifacts=(
                Artifact(type=ArtifactType.VIDEO, path="cyc/video/demo.webm", label="demo"),
                Artifact(type=ArtifactType.SCREENSHOT, path="cyc/screenshot/a.png", label="a"),
            ),
        )
        assert report.thumbnail_path == "cyc/screenshot/a.png"

    def test_thumbnail_path_falls_back_to_story_screenshot(self):
        story = StoryReport(
            ticket_id="T-1",
            title="t",
            status="completed",
            screenshots_after=(
                Artifact(type=ArtifactType.SCREENSHOT, path="cyc/screenshot/after.png", label="after"),
            ),
        )
        report = DemoReport(
            id="r2",
            cycle_id=CycleId("cyc-r2"),
            project_id="p",
            stories=(story,),
        )
        assert report.thumbnail_path == "cyc/screenshot/after.png"

    def test_thumbnail_path_none_when_no_screenshots(self):
        report = DemoReport(id="r3", cycle_id=CycleId("cyc-r3"), project_id="p")
        assert report.thumbnail_path is None

    async def test_browse_renders_img_when_thumbnail_present(self, db, tmp_path):
        project_repo = SQLiteProjectRepository(db)
        cycle_repo = SQLiteCycleRepository(db)
        report_repo = SQLiteReportRepository(db)
        await project_repo.save(Project(id="gamma", repo=RepoUrl("o/gamma")))

        report = DemoReport(
            id="gamma-1",
            cycle_id=CycleId("cyc-gamma-1"),
            project_id="gamma",
            created_at=datetime(2026, 4, 15, tzinfo=timezone.utc),
            summary=ReportSummary(stories_completed=1, stories_total=1),
            artifacts=(
                Artifact(
                    type=ArtifactType.SCREENSHOT,
                    path="cyc-gamma-1/screenshot/hero.png",
                    label="hero",
                ),
            ),
        )
        await report_repo.save(report)

        bus = EventBus()
        hub = SSEHub()
        app = create_web_app(project_repo, cycle_repo, bus, hub, report_repo=report_repo)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/demos/")

        assert r.status_code == 200
        assert 'data-testid="demo-thumbnail"' in r.text
        assert "/artifacts/cyc-gamma-1/screenshot/hero.png" in r.text
