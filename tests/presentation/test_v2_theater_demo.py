"""The theater ends on the demo (#79: "do this feature, create the demo,
show the demo to the user").

The person who pressed Play watches the theater. When the cycle was done
the theater said "completed" and stopped: the demo was on the repo page
and the player, and nothing here pointed to it (docs/demos/v2-play-to-demo.webm
had to go through the repo page). The report is saved just after the
cycle is marked completed, so the page keeps polling until it is there.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker
from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


async def _stage(tmp_path, status: str, *, with_report: bool) -> str:
    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=397))
    tracker.update_status(record.id, CycleStatus(status))
    conn = await init_db(str(tmp_path / "t.db"))
    reports = SQLiteReportRepository(conn)
    if with_report:
        await reports.save(DemoReport(
            id="rpt-c60953aa", cycle_id=CycleId(record.id), project_id="jrechet/concert-tour-app",
            created_at=datetime(2026, 9, 28, 16, 58, tzinfo=timezone.utc),
            summary=ReportSummary(stories_completed=3, stories_total=3, prs_merged=3),
            artifacts=(Artifact(type=ArtifactType.VIDEO, label="demo_recording",
                                path="20260928/video/demo.webm", mime_type="video/webm"),),
        ))
    try:
        app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
                             EventBus(), SSEHub(), base_path="/swarm", db=conn, report_repo=reports)
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issue = AsyncMock(return_value={"number": 397, "title": "Next concert"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                return (await client.get(f"/cycles/{record.id}/stage")).text
    finally:
        tracker._cycles.pop(record.id, None)
        await conn.close()


async def test_a_completed_cycle_shows_its_demo(tmp_path):
    html = await _stage(tmp_path, "completed", with_report=True)

    assert 'data-testid="stage-demo"' in html
    assert 'href="/swarm/demos/rpt-c60953aa"' in html
    assert "/swarm/artifacts/20260928/video/demo.webm" in html
    assert "3 PRs merged" in html
    assert "data-demo-pending" not in html


async def test_a_completed_cycle_without_its_report_yet_keeps_the_page_polling(tmp_path):
    html = await _stage(tmp_path, "completed", with_report=False)

    assert 'data-testid="stage-demo"' not in html
    assert "data-demo-pending" in html
    assert "Recording the demo" in html


async def test_a_running_cycle_has_no_demo_yet_and_says_nothing_of_it(tmp_path):
    html = await _stage(tmp_path, "running", with_report=False)

    assert 'data-testid="stage-demo"' not in html and "data-demo-pending" not in html


async def test_a_failed_cycle_does_not_wait_for_a_demo(tmp_path):
    html = await _stage(tmp_path, "failed", with_report=False)

    assert "data-demo-pending" not in html


def test_the_poll_loop_keeps_going_while_the_demo_is_pending():
    from pathlib import Path

    js = Path("src/theswarm/presentation/web/templates/v3/theater.html").read_text()

    assert "data-demo-pending" in js
