"""Open the project, watch the last demo.

The QA phase records a demo after every cycle — screenshots, a video, the
numbers — and stored it three clicks deep in the legacy pages. The project
page is where the owner starts from, so the latest one lives there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

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

REPO = "jrechet/concert-tour-app"


@pytest.fixture(autouse=True)
def _isolate_tracker():
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    yield
    tracker._cycles.clear()
    tracker._cycles.update(before)


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    if getattr(app.state, "report_repo", None) is None:
        app.state.report_repo = SQLiteReportRepository(conn)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await conn.close()


def _report(rid="rep-1", *, project=REPO, when=None, with_video=True) -> DemoReport:
    artifacts = [Artifact(
        type=ArtifactType("screenshot"), label="homepage",
        path="20260915/screenshot/homepage_1.png",
    )]
    if with_video:
        artifacts.append(Artifact(
            type=ArtifactType("video"), label="recording",
            path="20260915/video/recording.webm",
        ))
    return DemoReport(
        id=rid, cycle_id=CycleId("cafe1234cafe"), project_id=project,
        created_at=when or datetime(2026, 9, 15, 15, 40, tzinfo=timezone.utc),
        summary=ReportSummary(
            stories_completed=3, stories_total=3, prs_merged=2, cost_usd=4.7,
        ),
        artifacts=tuple(artifacts),
    )


async def _page(client):
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=[])
        return await client.get(f"/r/{REPO}")


class TestTheCard:
    async def test_the_latest_demo_is_on_the_project_page(self, web):
        client, app = web
        await app.state.report_repo.save(_report())

        r = await _page(client)

        assert r.status_code == 200
        assert 'data-testid="latest-demo"' in r.text
        assert "/swarm/demos/rep-1/play" in r.text

    async def test_it_shows_the_video_with_the_screenshot_as_poster(self, web):
        client, app = web
        await app.state.report_repo.save(_report())

        r = await _page(client)

        assert 'src="/swarm/artifacts/20260915/video/recording.webm"' in r.text
        assert 'poster="/swarm/artifacts/20260915/screenshot/homepage_1.png"' in r.text

    async def test_without_a_video_the_screenshot_stands_in(self, web):
        client, app = web
        await app.state.report_repo.save(_report(with_video=False))

        r = await _page(client)

        assert "<video" not in r.text
        assert 'src="/swarm/artifacts/20260915/screenshot/homepage_1.png"' in r.text

    async def test_the_numbers_read_as_a_sentence(self, web):
        client, app = web
        await app.state.report_repo.save(_report())

        r = await _page(client)

        assert "2 PRs merged" in r.text
        assert "3/3 stories" in r.text
        assert "1 screenshot" in r.text
        assert "1 video" in r.text
        assert "$4.70" in r.text

    async def test_it_links_to_the_cycle(self, web):
        client, app = web
        await app.state.report_repo.save(_report())

        r = await _page(client)

        assert "/swarm/cycles/cafe1234cafe" in r.text

    async def test_the_newest_report_wins(self, web):
        client, app = web
        old = _report("rep-old", when=datetime(2026, 9, 1, tzinfo=timezone.utc))
        new = _report("rep-new", when=datetime(2026, 9, 15, tzinfo=timezone.utc))
        await app.state.report_repo.save(old)
        await app.state.report_repo.save(new)

        r = await _page(client)

        assert "/swarm/demos/rep-new/play" in r.text
        assert "/swarm/demos/rep-old/play" not in r.text


class TestWhenThereIsNothingToShow:
    async def test_no_demo_no_card(self, web):
        client, _ = web

        r = await _page(client)

        assert r.status_code == 200
        assert 'data-testid="latest-demo"' not in r.text

    async def test_another_projects_demo_stays_on_its_own_page(self, web):
        client, app = web
        await app.state.report_repo.save(_report(project="jrechet/theswarm"))

        r = await _page(client)

        assert 'data-testid="latest-demo"' not in r.text

    async def test_a_broken_report_store_does_not_take_the_page_down(self, web):
        client, app = web
        app.state.report_repo.list_by_project = AsyncMock(side_effect=RuntimeError("db locked"))

        r = await _page(client)

        assert r.status_code == 200
        assert 'data-testid="latest-demo"' not in r.text
        assert 'data-testid="composer"' in r.text

    async def test_no_report_store_at_all(self, web):
        client, app = web
        app.state.report_repo = None

        r = await _page(client)

        assert r.status_code == 200
        assert 'data-testid="composer"' in r.text
