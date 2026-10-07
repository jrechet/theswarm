"""V3, M3 — the project and the feature (docs/plans/2026-10-v3-one-product.md).

`/c/{slug}/p/{name}`: the composer (Create only / Create and play), the
board (Backlog, Ready with the stalled ones named, Building, In review,
Delivered from the demos), the trend, the recent cycles. `/f/{n}`: one
feature, its sub-tasks, its cycles, its demo. `/r/{owner}/{name}` (V2)
registers an unknown repository under Internal and redirects here.
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
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

REPO = "jrechet/espace-client"
PAGE = "/c/tlphone/p/espace-client"
HTML = {"accept": "text/html"}
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate_tracker():
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    tracker._cycles.clear()
    yield tracker
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
    tl = await app.state.customer_service.create("TLphone")
    await app.state.customer_service.assign_project(REPO, tl)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    await conn.close()


def _issue(number: int, status: str, title: str, body: str = "") -> dict:
    return {"number": number, "title": title, "body": body, "state": "open",
            "labels": [{"name": f"status:{status}"}, {"name": "role:dev"}], "html_url": f"https://github.com/{REPO}/issues/{number}"}


ISSUES = [
    _issue(10, "backlog", "Export invoices as PDF"),
    _issue(11, "ready", "Rate-limit the login endpoint"),
    _issue(12, "in-progress", "Harden input validation"),
    _issue(13, "in-progress", "Old building label, nothing runs"),
    _issue(14, "review", "Invoice numbering per year"),
]
PRS = [{"number": 83, "title": "[#14] Invoice numbering per year", "body": "Closes #14", "head": "feat/14"}]


def _github(issues=ISSUES, prs=PRS, created: dict | None = None):
    ctx = patch("theswarm.tools.github.GitHubClient")
    klass = ctx.start()
    client = klass.return_value
    client.get_issues = AsyncMock(return_value=list(issues))
    client.get_issue = AsyncMock(side_effect=lambda n: next((i for i in issues if i["number"] == n), None))
    client.get_open_pr_briefs = AsyncMock(return_value=list(prs))
    client.create_issue = AsyncMock(return_value=created or {"number": 15})
    return ctx


def _running(tracker, issue: int = 12, cycle_id: str = "abc123abc123"):
    from theswarm.api import CycleRecord, CycleStatus as TrackerStatus

    tracker._cycles[cycle_id] = CycleRecord(
        id=cycle_id, repo=REPO, description=f"Play on issue #{issue}", callback_url="",
        issue_number=issue, status=TrackerStatus.RUNNING, created_at="2026-10-07T08:00:00+00:00",
        started_at="2026-10-07T08:00:30+00:00",
    )


async def _cycle(app, cycle_id: str, issue: int, status=CycleStatus.COMPLETED, cost: float = 2.14) -> None:
    project = next(p for p in await app.state.project_repo.list_all() if str(p.repo) == REPO)
    await app.state.cycle_repo.save(Cycle(
        id=CycleId(cycle_id), project_id=project.id, status=status, triggered_by="web",
        started_at=NOW, completed_at=NOW.replace(hour=9, minute=44) if status == CycleStatus.COMPLETED else None,
        total_cost_usd=cost, prs_opened=(83,), prs_merged=(83,) if status == CycleStatus.COMPLETED else (),
        issue_number=issue,
    ))


def _report(rid: str, cycle_id: str, title: str = "Invoice numbering per year") -> DemoReport:
    return DemoReport(
        id=rid, cycle_id=CycleId(cycle_id), project_id=REPO, created_at=NOW,
        summary=ReportSummary(stories_completed=1, stories_total=1, prs_merged=1, cost_usd=2.14),
        stories=(StoryReport(ticket_id="14", title=title),),
    )


# ── The page ─────────────────────────────────────────────────────────


class TestThePage:
    async def test_the_board_has_its_columns_and_the_truth(self, web, _isolate_tracker):
        client, app = web
        _running(_isolate_tracker, issue=12)
        ctx = _github()
        try:
            r = await client.get(PAGE, headers=HTML)
        finally:
            ctx.stop()
        assert r.status_code == 200
        assert 'data-testid="project-page" data-project="jrechet/espace-client"' in r.text
        assert 'data-testid="running-banner"' in r.text and "/swarm/c/abc123abc123" in r.text
        for key in ("backlog", "ready", "in-progress", "review"):
            assert f'aria-labelledby="group-{key}"' in r.text
        building = r.text.split('data-column="in-progress"')[1].split("</section>")[0]
        assert "Harden input validation" in building and "Old building label" not in building
        assert 'aria-labelledby="group-stalled"' in r.text and "Old building label" in r.text.split('group-stalled')[1]
        review = r.text.split('data-column="review"')[1].split("</section>")[0]
        assert "Invoice numbering per year" in review
        assert 'data-testid="play-10"' in r.text and 'data-testid="play-13"' in r.text
        assert f'href="/swarm{PAGE}/f/10"' in r.text

    async def test_the_rail_marks_the_project_inside_its_customer(self, web):
        client, app = web
        ctx = _github()
        try:
            r = await client.get(PAGE, headers=HTML)
        finally:
            ctx.stop()
        rail = r.text.split('data-testid="rail"')[1].split("</nav>")[0]
        assert f'href="/swarm{PAGE}"' in rail
        assert 'data-testid="rail-project" data-running="false"' in rail
        assert "bg-raised text-ink font-medium" in rail.split('data-testid="rail-project"')[1][:400]

    async def test_delivered_and_the_recent_cycles_come_from_the_database(self, web):
        client, app = web
        await _cycle(app, "cafe1234cafe", issue=14)
        await _cycle(app, "dead1234dead", issue=11, status=CycleStatus.FAILED, cost=0.4)
        await app.state.report_repo.save(_report("rep-1", "cafe1234cafe"))
        ctx = _github()
        try:
            r = await client.get(PAGE, headers=HTML)
        finally:
            ctx.stop()
        assert 'data-testid="latest-demo"' in r.text and "/swarm/demos/rep-1/play" in r.text
        recent = r.text.split('data-testid="recent-cycles"')[1].split("</section>")[0]
        assert "cafe1234" in recent and "dead1234" in recent
        assert ">Completed<" in recent and ">Failed<" in recent
        assert "44 min" in recent and "$2.14" in recent
        assert "Demo →" in recent

    async def test_an_unknown_project_or_customer_is_404(self, web):
        client, app = web
        assert (await client.get("/c/tlphone/p/nothing", headers=HTML)).status_code == 404
        assert (await client.get("/c/nobody/p/espace-client", headers=HTML)).status_code == 404

    async def test_github_down_keeps_the_page_with_its_error(self, web):
        client, app = web
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issues = AsyncMock(side_effect=RuntimeError("bad credentials"))
            r = await client.get(PAGE, headers=HTML)
        assert r.status_code == 200 and 'data-testid="issues-error"' in r.text and "bad credentials" in r.text


class TestTheV2Address:
    async def test_a_v2_link_registers_under_internal_and_redirects(self, web):
        client, app = web
        r = await client.get("/r/jrechet/concert-tour-app?new=7", headers=HTML)
        assert r.status_code == 303
        assert r.headers["location"] == "/swarm/c/internal/p/concert-tour-app?new=7"
        assert any(str(p.repo) == "jrechet/concert-tour-app" for p in await app.state.project_repo.list_all())

    async def test_a_v2_link_to_a_customer_s_project_goes_to_its_customer(self, web):
        client, app = web
        r = await client.get(f"/r/{REPO}", headers=HTML)
        assert r.headers["location"] == f"/swarm{PAGE}"


# ── The composer and Play ────────────────────────────────────────────


class TestTheComposer:
    async def test_create_only_lands_on_the_fresh_issue(self, web):
        client, app = web
        ctx = _github(created={"number": 15})
        try:
            r = await client.post(f"{PAGE}/features", data={"body": "Export invoices as PDF\nMonthly, one file.", "play": ""})
            assert r.status_code == 303 and r.headers["location"] == f"/swarm{PAGE}?new=15"
            from theswarm.tools.github import GitHubClient

            GitHubClient.return_value.create_issue.assert_awaited_once_with(
                title="Export invoices as PDF", body="Monthly, one file.", labels=["status:backlog"],
            )
            fresh = dict(_issue(15, "backlog", "Export invoices as PDF"))
            GitHubClient.return_value.get_issue = AsyncMock(return_value=fresh)
            r = await client.get(f"{PAGE}?new=15", headers=HTML)
        finally:
            ctx.stop()
        assert 'data-testid="fresh-issue"' in r.text and "Export invoices as PDF" in r.text

    async def test_create_and_play_starts_a_cycle_and_opens_the_theater(self, web):
        client, app = web
        ctx = _github(created={"number": 15})
        try:
            with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle",
                       new=AsyncMock(return_value=type("R", (), {"id": "cyc123cyc123"})())) as start:
                r = await client.post(f"{PAGE}/features", data={"body": "Export invoices as PDF", "play": "1"})
        finally:
            ctx.stop()
        assert r.status_code == 303 and r.headers["location"] == "/swarm/c/cyc123cyc123"
        start.assert_awaited_once()
        assert start.await_args.args[1:4] == ("jrechet", "espace-client", 15)

    async def test_an_empty_composer_goes_back(self, web):
        client, app = web
        r = await client.post(f"{PAGE}/features", data={"body": "   "})
        assert r.status_code == 303 and r.headers["location"] == f"/swarm{PAGE}"

    async def test_play_on_a_feature(self, web):
        client, app = web
        with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle",
                   new=AsyncMock(return_value=type("R", (), {"id": "cyc123cyc123"})())) as start:
            r = await client.post(f"{PAGE}/features/11/play")
        assert r.status_code == 303 and r.headers["location"] == "/swarm/c/cyc123cyc123"
        assert start.await_args.args[3] == 11


# ── One feature ──────────────────────────────────────────────────────


class TestTheFeature:
    async def test_the_feature_shows_its_pieces_and_its_cycles(self, web, _isolate_tracker):
        client, app = web
        story = _issue(20, "in-progress", "Harden input validation", "Reject malformed JSON, map validation errors.")
        children = [
            {**_issue(21, "review", "Reject malformed JSON with 400", "Parent: #20"), "state": "closed", "state_reason": "completed"},
            _issue(22, "in-progress", "Validation exception mapper", "Parent: #20"),
            {**_issue(23, "ready", "Sanitize free-text fields", "Parent: #20"), "state": "closed", "state_reason": "not_planned"},
            _issue(24, "ready", "Unrelated", "Parent: #200"),
        ]
        _running(_isolate_tracker, issue=20)
        await _cycle(app, "cafe1234cafe", issue=20)
        await app.state.report_repo.save(_report("rep-20", "cafe1234cafe", "Harden input validation"))
        ctx = _github(issues=[story, *children])
        try:
            r = await client.get(f"{PAGE}/f/20", headers=HTML)
        finally:
            ctx.stop()
        assert r.status_code == 200
        assert 'data-testid="feature-page" data-number="20"' in r.text
        assert "Reject malformed JSON, map validation errors." in r.text
        assert 'data-testid="feature-status"' in r.text and 'data-kind="running"' in r.text
        assert r.text.count('data-testid="sub-task"') == 3 and "Unrelated" not in r.text
        assert 'data-status="done"' in r.text and 'data-status="dropped"' in r.text and 'data-status="in-progress"' in r.text
        assert "1 of 3 sub-tasks done" in r.text
        assert 'data-testid="follow"' in r.text and "/swarm/c/abc123abc123" in r.text
        assert "cafe1234" in r.text and 'data-testid="feature-demo"' in r.text and "/swarm/demos/rep-20/play" in r.text

    async def test_a_feature_nobody_builds_offers_play(self, web):
        client, app = web
        ctx = _github()
        try:
            r = await client.get(f"{PAGE}/f/11", headers=HTML)
        finally:
            ctx.stop()
        assert 'data-testid="play"' in r.text and f'action="/swarm{PAGE}/features/11/play"' in r.text
        assert "Not broken down yet" in r.text

    async def test_an_unknown_feature_is_404(self, web):
        client, app = web
        ctx = _github()
        try:
            r = await client.get(f"{PAGE}/f/999", headers=HTML)
        finally:
            ctx.stop()
        assert r.status_code == 404
