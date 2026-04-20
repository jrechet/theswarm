"""Sprint C F5 — Public shareable demo URL /d/{short}."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
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
    conn = await init_db(str(tmp_path / "public.db"))
    yield conn
    await conn.close()


@pytest.fixture
async def app_and_report(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    report_repo = SQLiteReportRepository(db)

    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
    report = DemoReport(
        id="report-abc-123",
        cycle_id=CycleId("cyc-1"),
        project_id="alpha",
        created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        summary=ReportSummary(stories_completed=1, stories_total=1),
    )
    await report_repo.save(report)

    bus = EventBus()
    hub = SSEHub()
    app = create_web_app(
        project_repo, cycle_repo, bus, hub,
        report_repo=report_repo, db=db,
    )
    return app, report


def test_public_slug_is_deterministic_and_short():
    r = DemoReport(id="hello", cycle_id=CycleId("c"), project_id="p")
    slug = r.public_slug
    assert len(slug) == 8
    assert slug == DemoReport(id="hello", cycle_id=CycleId("x"), project_id="q").public_slug


def test_public_slug_varies_by_id():
    a = DemoReport(id="a", cycle_id=CycleId("c"), project_id="p")
    b = DemoReport(id="b", cycle_id=CycleId("c"), project_id="p")
    assert a.public_slug != b.public_slug


async def test_public_url_renders_player(app_and_report):
    app, report = app_and_report
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/d/{report.public_slug}")
    assert r.status_code == 200
    assert "player-stage" in r.text
    # Public marker rendered
    assert "player-public-badge" in r.text


async def test_public_url_hides_approve_controls(app_and_report):
    app, report = app_and_report
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/d/{report.public_slug}")
    assert r.status_code == 200
    assert "story-action-form" not in r.text


async def test_unknown_slug_returns_404(app_and_report):
    app, _ = app_and_report
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/d/deadbeef")
    assert r.status_code == 404
