"""Sprint F F8 — A/B demo comparator route."""

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


def _make_report(report_id: str, project_id: str, *, has_video: bool = True) -> DemoReport:
    artifacts: tuple[Artifact, ...] = ()
    if has_video:
        artifacts = (
            Artifact(
                type=ArtifactType.VIDEO,
                path=f"{report_id}/demo.webm",
                label=f"{project_id} walkthrough",
            ),
            Artifact(
                type=ArtifactType.SCREENSHOT,
                path=f"{report_id}/shot.png",
                label="Dashboard",
            ),
        )
    return DemoReport(
        id=report_id,
        cycle_id=CycleId(f"cyc-{report_id}"),
        project_id=project_id,
        created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        summary=ReportSummary(stories_completed=1, stories_total=1, prs_merged=1),
        stories=(
            StoryReport(
                ticket_id="T-1",
                title=f"Feature for {project_id}",
                status="completed",
                pr_number=1,
            ),
        ),
        artifacts=artifacts,
    )


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "compare.db"))
    yield conn
    await conn.close()


@pytest.fixture
async def app(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    report_repo = SQLiteReportRepository(db)

    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
    await project_repo.save(Project(id="beta", repo=RepoUrl("o/beta")))

    await report_repo.save(_make_report("rep-a", "alpha"))
    await report_repo.save(_make_report("rep-b", "beta"))

    return create_web_app(
        project_repo, cycle_repo, EventBus(), SSEHub(),
        report_repo=report_repo,
        db=db,
    )


async def test_compare_renders_both_panels(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/demos/compare", params={"a": "rep-a", "b": "rep-b"})
    assert r.status_code == 200
    assert "alpha" in r.text
    assert "beta" in r.text
    assert 'data-panel="A"' in r.text
    assert 'data-panel="B"' in r.text
    assert "compare-video" in r.text
    assert "compare-scrub" in r.text


async def test_compare_missing_a_returns_404(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/demos/compare", params={"a": "nope", "b": "rep-b"})
    assert r.status_code == 404


async def test_compare_missing_b_returns_404(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/demos/compare", params={"a": "rep-a", "b": "nope"})
    assert r.status_code == 404


async def test_compare_requires_query_params(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/demos/compare")
    assert r.status_code == 422


async def test_compare_panels_show_video_when_present(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/demos/compare", params={"a": "rep-a", "b": "rep-b"})
    assert r.status_code == 200
    assert "rep-a/demo.webm" in r.text
    assert "rep-b/demo.webm" in r.text
