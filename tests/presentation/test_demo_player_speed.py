"""Sprint F F7 — Player speed control renders in demo player template."""

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
    conn = await init_db(str(tmp_path / "speed.db"))
    yield conn
    await conn.close()


@pytest.fixture
async def app(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    report_repo = SQLiteReportRepository(db)

    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))

    story = StoryReport(
        ticket_id="T-1",
        title="Something",
        status="completed",
        pr_number=1,
    )
    report = DemoReport(
        id="r-speed",
        cycle_id=CycleId("cyc-1"),
        project_id="alpha",
        created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        summary=ReportSummary(stories_completed=1, stories_total=1),
        stories=(story,),
    )
    await report_repo.save(report)

    return create_web_app(
        project_repo, cycle_repo, EventBus(), SSEHub(),
        report_repo=report_repo,
        db=db,
    )


async def test_speed_buttons_render_in_player(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/demos/r-speed/play")
    assert r.status_code == 200
    assert 'data-speed="0.5"' in r.text
    assert 'data-speed="1"' in r.text
    assert 'data-speed="2"' in r.text
    assert "player-speed-group" in r.text
    assert "player-speed-btn" in r.text
