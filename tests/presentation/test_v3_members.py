"""V3, M5 — what a member sees (docs/plans/2026-10-v3-one-product.md).

A request is the one thing a customer writes: Nadia sends one, it lands in
the owner's inbox (the home, the rail's badge); the owner turns it into a
feature — the GitHub issue on one of TLphone's projects — and the request
follows that feature's cycle: building when a cycle starts on the issue,
delivered when its demo lands. A member's overview shows what is being
built as four plain steps, the latest demos and their requests; their
feature page and the player show no cost, no cycle, no link into the
machinery. The owner can look at it all as a member (`?as=member`).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.services import pinned_issue
from theswarm.domain.cycles.events import CycleStarted
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.events import DemoReady
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType, QualityGate, QualityStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web import member_steps
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.auth import SESSION_COOKIE
from theswarm.presentation.web.sse import SSEHub

KEY = "k-tlphone-test"
SECRET = "s" * 32
HTML = {"accept": "text/html"}
REPO = "jrechet/espace-client"
FEATURE = "/c/tlphone/p/espace-client/f/42"
NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _wall(monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", SECRET)
    monkeypatch.setenv("SWARM_ACCESS_KEY", KEY)
    monkeypatch.delenv("EXTERNAL_URL", raising=False)
    pinned_issue.clear_cache()


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
async def app(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), db=conn,
    )
    if getattr(app.state, "report_repo", None) is None:
        app.state.report_repo = SQLiteReportRepository(conn)
    yield app
    await conn.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture()
async def owner(app):
    async with _client(app) as client:
        r = await client.post("/login", data={"access_key": KEY})
        assert r.status_code == 303
        yield client


@pytest.fixture()
async def visitor(app):
    async with _client(app) as client:
        yield client


def _home(client):
    with patch("theswarm.presentation.web.routes.v2.github_app") as gh:
        gh.load_credentials = AsyncMock(return_value=None)
        gh.list_user_repositories = AsyncMock(return_value=[])
        gh.oauth_client = AsyncMock(return_value=object())
        return client.get("/", headers=HTML)


async def _nadia(owner, visitor) -> str:
    """TLphone with espace-client, Nadia invited and signed in; the slug."""
    r = await owner.post("/settings/customers", data={"name": "TLphone"})
    assert r.status_code == 303
    r = await owner.post("/settings/customers/tlphone/projects", data={"full_name": REPO})
    assert r.status_code == 303
    r = await owner.post("/settings/customers/tlphone/members", data={"email": "nadia@tlphone.fr", "display_name": "Nadia"})
    assert r.status_code == 200
    link = re.search(r'value="(http://test/invite/[^"]+)"', r.text).group(1).replace("http://test", "")
    r = await visitor.get(link)
    assert r.status_code == 303 and SESSION_COOKIE in visitor.cookies
    return "tlphone"


async def _request(visitor, title: str = "Export invoices as PDF", body: str = "Monthly, for accounting") -> str:
    """Nadia sends a request; its id, read back from her list."""
    r = await visitor.post("/requests", data={"title": title, "body": body, "project": REPO})
    assert r.status_code == 303 and r.headers["location"].endswith("/requests")
    r = await visitor.get("/requests", headers=HTML)
    assert r.status_code == 200
    match = re.search(r'data-testid="my-request" data-status="received" data-request="([0-9a-f]+)"', r.text)
    assert match, "her list names the request"
    return match.group(1)


def _issue(number: int, title: str, status: str = "backlog", state: str = "open", body: str = "") -> dict:
    return {"number": number, "title": title, "body": body, "state": state,
            "labels": [{"name": f"status:{status}"}], "html_url": f"https://github.com/{REPO}/issues/{number}"}


def _github(issues=(), created: dict | None = None):
    """GitHub stubbed: the issues the pinned-issue loader reads, the one the plan creates."""
    issues = list(issues)
    ctx = patch("theswarm.tools.github.GitHubClient")
    klass = ctx.start()
    client = klass.return_value
    client.get_issues = AsyncMock(return_value=issues)
    client.get_issue = AsyncMock(side_effect=lambda n: next((i for i in issues if i["number"] == n), None))
    client.get_open_pr_briefs = AsyncMock(return_value=[])
    client.create_issue = AsyncMock(return_value=created or {"number": 42})
    return ctx, client


async def _plan(owner, request_id: str, number: int = 42) -> AsyncMock:
    ctx, client = _github(issues=[_issue(number, "Export invoices as PDF")], created={"number": number})
    try:
        r = await owner.post(f"/requests/{request_id}/plan", data={"project": REPO, "title": "Export invoices as PDF"})
    finally:
        ctx.stop()
    assert r.status_code == 303, r.text[:300]
    assert r.headers["location"].endswith(f"/c/tlphone/p/espace-client/f/{number}")
    return client.create_issue


def _running(tracker, issue: int = 42, cycle_id: str = "abc123abc123", phase: str = "dev_iter"):
    from theswarm.api import CycleRecord, CycleStatus
    from theswarm.application.services.progress_bridge import record_phase

    tracker._cycles[cycle_id] = CycleRecord(
        id=cycle_id, repo=REPO, description=f"Play on issue #{issue}", callback_url="",
        issue_number=issue, status=CycleStatus.RUNNING, created_at="2026-10-07T13:00:00+00:00",
        started_at="2026-10-07T13:00:30+00:00",
    )
    for p in ("prepare", "po_morning", "techlead_breakdown", phase):
        record_phase(cycle_id, p)
        if p == phase:
            break


def _gate(name, status, detail=""):
    return QualityGate(name=name, status=QualityStatus(status), detail=detail)


def _report(rid: str = "rep-1", project_id: str = REPO, *, gates=(), when=NOW) -> DemoReport:
    return DemoReport(
        id=rid, cycle_id=CycleId("cafe1234cafe"), project_id=project_id, created_at=when,
        summary=ReportSummary(stories_completed=1, stories_total=1, prs_merged=1, cost_usd=2.77),
        stories=(StoryReport(ticket_id="42", title="Export invoices as PDF", status="completed", pr_number=82),),
        quality_gates=tuple(gates),
        artifacts=(Artifact(type=ArtifactType("screenshot"), label="home", path="cafe1234cafe/home.png"),
                   Artifact(type=ArtifactType("video"), label="walk", path="cafe1234cafe/walk.webm")),
    )


# ── The four steps, pure ─────────────────────────────────────────────


class TestTheFourSteps:
    def test_a_running_cycle_lights_the_step_of_its_phase(self):
        stage = member_steps.stage_for("qa", "running")
        assert stage["key"] == "building" and stage["live"]
        assert [s["state"] for s in stage["steps"]] == ["done", "done", "now", "next"]
        assert member_steps.stage_for("techlead_breakdown", "queued")["steps"][0]["state"] == "now"
        assert member_steps.stage_for("merge_held", "running")["steps"][3]["state"] == "now"

    def test_a_finished_cycle_is_delivered_once_its_demo_is_stored(self):
        assert member_steps.stage_for("po_evening", "completed", has_demo=True)["key"] == "delivered"
        finishing = member_steps.stage_for("po_evening", "completed", has_demo=False)
        assert finishing["key"] == "finishing" and finishing["steps"][3]["state"] == "now"

    def test_a_stopped_cycle_and_a_feature_not_started(self):
        stopped = member_steps.stage_for("dev_iter", "failed")
        assert stopped["key"] == "stopped" and [s["state"] for s in stopped["steps"]] == ["done", "off", "next", "next"]
        assert member_steps.stage_for("", "")["key"] == "planned"
        assert member_steps.stage_for("", "", closed=True)["key"] == "delivered"
        assert [s["label"] for s in member_steps.stage_for()["steps"]] == ["Planning", "Building", "Checking", "Delivered"]


# ── A request, from Nadia to the inbox and back ──────────────────────


class TestARequest:
    async def test_nadia_sends_a_request_and_sees_it_received(self, owner, visitor):
        await _nadia(owner, visitor)
        r = await visitor.get("/requests/new", headers=HTML)
        assert r.status_code == 200 and 'data-testid="request-new"' in r.text
        await _request(visitor)

        r = await visitor.get("/requests", headers=HTML)
        assert 'data-testid="requests-page" data-role="member"' in r.text
        assert 'data-testid="my-request" data-status="received"' in r.text
        assert 'data-step="received" data-state="now"' in r.text and 'data-step="planned" data-state="next"' in r.text
        assert "Export invoices as PDF" in r.text and 'data-testid="rail-requests"' in r.text

        r = await visitor.get("/c/tlphone", headers=HTML)
        assert 'data-testid="member-request" data-status="received"' in r.text
        assert 'data-testid="new-request"' in r.text

    async def test_an_empty_request_is_refused(self, owner, visitor):
        await _nadia(owner, visitor)
        r = await visitor.post("/requests", data={"title": "   ", "project": REPO})
        assert r.status_code == 303 and "/requests/new?error=" in r.headers["location"]
        r = await visitor.get("/requests/new?error=Say+what+you+need+in+one+line.", headers=HTML)
        assert 'data-testid="error"' in r.text

    async def test_the_owner_finds_it_on_the_home_the_rail_and_the_inbox(self, owner, visitor):
        await _nadia(owner, visitor)
        request_id = await _request(visitor)

        r = await _home(owner)
        assert r.status_code == 200
        assert 'data-testid="requests-waiting"' in r.text and 'data-testid="home-request"' in r.text
        assert "TLphone" in r.text and "Nadia" in r.text and "1 waiting for you" in r.text
        assert re.search(r'data-testid="rail-requests"[^>]*>.*?>1<', r.text, re.S), "the rail's badge counts it"

        r = await owner.get("/requests", headers=HTML)
        assert 'data-testid="requests-page" data-role="owner"' in r.text
        assert f'data-testid="inbox-request" data-request="{request_id}"' in r.text
        assert "Monthly, for accounting" in r.text and 'value="jrechet/espace-client"' in r.text
        assert 'data-testid="plan"' in r.text and 'data-testid="decline"' in r.text

    async def test_the_owner_turns_it_into_a_feature(self, owner, visitor):
        await _nadia(owner, visitor)
        request_id = await _request(visitor)
        create_issue = await _plan(owner, request_id)

        kwargs = create_issue.call_args.kwargs
        assert kwargs["title"] == "Export invoices as PDF" and kwargs["labels"] == ["status:backlog"]
        assert "Monthly, for accounting" in kwargs["body"] and "Requested by Nadia (TLphone)" in kwargs["body"]
        assert f"<!-- swarm:request {request_id} -->" in kwargs["body"]

        r = await owner.get("/requests", headers=HTML)
        assert 'data-testid="inbox-request"' not in r.text
        assert 'data-testid="open-request" data-status="planned"' in r.text and "espace-client#42" in r.text
        r = await _home(owner)
        assert 'data-testid="requests-waiting"' not in r.text

        r = await visitor.get("/requests", headers=HTML)
        assert 'data-testid="my-request" data-status="planned"' in r.text
        assert 'data-step="received" data-state="done"' in r.text and 'data-step="planned" data-state="now"' in r.text

    async def test_building_and_delivered_follow_the_feature_s_cycle(self, app, owner, visitor):
        await _nadia(owner, visitor)
        request_id = await _request(visitor)
        await _plan(owner, request_id)

        await app.state.event_bus.publish(CycleStarted(cycle_id=CycleId("abc123abc123"), project_id=REPO, issue_number=42))
        r = await visitor.get("/requests", headers=HTML)
        assert 'data-testid="my-request" data-status="building"' in r.text
        assert 'data-step="building" data-state="now"' in r.text

        await app.state.report_repo.save(_report("rep-1"))
        await app.state.event_bus.publish(DemoReady(cycle_id=CycleId("abc123abc123"), project_id=REPO,
                                                    report_id="rep-1", issue_number=42))
        r = await visitor.get("/requests", headers=HTML)
        assert 'data-testid="my-request" data-status="delivered"' in r.text
        assert 'data-step="delivered" data-state="done"' in r.text
        assert 'data-testid="my-demo"' in r.text and 'href="/demos/rep-1"' in r.text

        # A cycle on another issue, or another repository, moves nothing.
        r = await owner.get("/requests", headers=HTML)
        assert 'data-testid="open-request"' not in r.text

    async def test_the_owner_declines_with_a_reason(self, owner, visitor):
        await _nadia(owner, visitor)
        request_id = await _request(visitor, title="Rewrite everything in Rust")
        r = await owner.post(f"/requests/{request_id}/decline", data={"reason": "Not this quarter"})
        assert r.status_code == 303
        r = await visitor.get("/requests", headers=HTML)
        assert 'data-testid="my-request" data-status="declined"' in r.text and "declined: Not this quarter" in r.text
        assert 'data-step="planned" data-state="off"' in r.text

    async def test_a_member_may_neither_plan_nor_decline(self, owner, visitor):
        await _nadia(owner, visitor)
        request_id = await _request(visitor)
        r = await visitor.post(f"/requests/{request_id}/plan", data={"project": REPO}, headers=HTML)
        assert r.status_code == 403
        r = await visitor.post(f"/requests/{request_id}/decline", data={"reason": "no"}, headers=HTML)
        assert r.status_code == 403
        r = await owner.get("/requests/new", headers=HTML)
        assert r.status_code == 403  # the composer is a member's

    async def test_planning_needs_one_of_the_customer_s_projects(self, owner, visitor):
        await _nadia(owner, visitor)
        request_id = await _request(visitor)
        r = await owner.post(f"/requests/{request_id}/plan", data={"project": "someone/else"})
        assert r.status_code == 303 and "error=Pick+one" in r.headers["location"]
        r = await owner.post("/requests/nope/plan", data={"project": REPO})
        assert r.status_code == 404


# ── What a member sees ───────────────────────────────────────────────


class TestTheOverview:
    async def test_what_is_being_built_as_four_steps_the_demos_and_the_counts(self, app, owner, visitor, _isolate_tracker):
        await _nadia(owner, visitor)
        _running(_isolate_tracker, issue=42, phase="dev_iter")
        await app.state.report_repo.save(_report("rep-1", gates=(_gate("feature_e2e", "pass"), _gate("feature_pages", "pass"))))
        ctx, _ = _github(issues=[_issue(42, "Export invoices as PDF", "in-progress")])
        try:
            r = await visitor.get("/c/tlphone", headers=HTML)
        finally:
            ctx.stop()
        assert r.status_code == 200
        assert 'data-testid="customer-page" data-slug="tlphone" data-view="member"' in r.text
        assert "Hello, Nadia" in r.text and 'data-testid="member-stats"' in r.text
        assert 'data-testid="member-building"' in r.text and "Export invoices as PDF" in r.text
        assert f'href="{FEATURE}"' in r.text
        assert 'data-step="build" data-state="now"' in r.text and 'data-step="plan" data-state="done"' in r.text
        assert 'data-testid="member-demo"' in r.text and 'href="/demos/rep-1"' in r.text and ">Verified<" in r.text
        assert "/cycles/" not in r.text and "$2.77" not in r.text and "abc123ab" not in r.text

    async def test_an_idle_customer_says_so(self, owner, visitor):
        await _nadia(owner, visitor)
        r = await visitor.get("/c/tlphone", headers=HTML)
        assert 'data-testid="member-idle"' in r.text and "No demo yet" in r.text

    async def test_the_owner_views_the_customer_as_a_member(self, owner, visitor):
        await _nadia(owner, visitor)
        r = await owner.get("/c/tlphone", headers=HTML)
        assert 'data-testid="view-as"' in r.text and 'data-view="owner"' in r.text
        assert 'data-testid="customer-project"' in r.text
        r = await owner.get("/c/tlphone?as=member", headers=HTML)
        assert 'data-testid="view-as-banner"' in r.text and 'data-view="member"' in r.text
        assert 'data-testid="member-stats"' in r.text and 'data-testid="new-request"' not in r.text


class TestAMembersFeature:
    async def test_the_four_steps_while_it_is_built(self, owner, visitor, _isolate_tracker):
        await _nadia(owner, visitor)
        _running(_isolate_tracker, issue=42, phase="qa")
        ctx, _ = _github(issues=[_issue(42, "Export invoices as PDF", "in-progress")])
        try:
            r = await visitor.get(FEATURE, headers=HTML)
        finally:
            ctx.stop()
        assert r.status_code == 200, r.text[:300]
        assert 'data-testid="feature-member" data-number="42"' in r.text
        assert 'data-testid="member-steps" data-stage="building"' in r.text
        assert 'data-step="check" data-state="now"' in r.text
        assert "Being built right now" in r.text and "checked against the running app" in r.text
        assert "/cycles/" not in r.text and "github.com" not in r.text and 'data-testid="play"' not in r.text

    async def test_planned_before_any_cycle_and_delivered_after_its_demo(self, app, owner, visitor):
        await _nadia(owner, visitor)
        ctx, _ = _github(issues=[_issue(42, "Export invoices as PDF", "ready")])
        try:
            r = await visitor.get(FEATURE, headers=HTML)
            assert r.status_code == 200 and 'data-stage="planned"' in r.text
            pinned_issue.clear_cache()

            from theswarm.domain.cycles.entities import Cycle
            from theswarm.domain.cycles.value_objects import CycleStatus

            await app.state.cycle_repo.save(Cycle(
                id=CycleId("cafe1234cafe"), project_id=REPO, status=CycleStatus.COMPLETED, triggered_by="web",
                started_at=NOW, completed_at=NOW, issue_number=42,
            ))
            await app.state.report_repo.save(_report("rep-1"))
            r = await visitor.get(FEATURE, headers=HTML)
        finally:
            ctx.stop()
        assert 'data-stage="delivered"' in r.text and 'data-testid="member-demo"' in r.text
        assert 'href="/demos/rep-1"' in r.text and "$" not in r.text

    async def test_the_request_marker_is_not_shown_on_either_feature_page(self, owner, visitor):
        await _nadia(owner, visitor)
        body = "Toutes nos salles, triées par nom.\n\nRequested by Nadia (TLphone), 07 Oct 2026.\n\n<!-- swarm:request 65ae5d7f357c -->"
        ctx, _ = _github(issues=[_issue(42, "Export invoices as PDF", "backlog", body=body)])
        try:
            member = await visitor.get(FEATURE, headers=HTML)
            pinned_issue.clear_cache()
            page = await owner.get(FEATURE, headers=HTML)
        finally:
            ctx.stop()
        for r in (member, page):
            assert r.status_code == 200
            assert "swarm:request" not in r.text and "Requested by Nadia (TLphone)" in r.text
            assert "Toutes nos salles" in r.text

    async def test_another_customer_s_feature_is_refused(self, owner, visitor):
        await _nadia(owner, visitor)
        await owner.post("/settings/customers", data={"name": "Yakoi"})
        await owner.post("/settings/customers/yakoi/projects", data={"full_name": "jrechet/yakoi"})
        r = await visitor.get("/c/yakoi/p/yakoi/f/1", headers=HTML)
        assert r.status_code == 403 and 'data-testid="refused"' in r.text


class TestAMembersDemo:
    async def test_the_player_without_the_cost_or_the_links(self, app, owner, visitor):
        await _nadia(owner, visitor)
        await app.state.report_repo.save(_report("rep-1"))
        r = await visitor.get("/demos/rep-1", headers=HTML)
        assert r.status_code == 200 and 'data-testid="player" data-report="rep-1"' in r.text
        assert "$2.77" not in r.text and 'data-testid="visibility"' not in r.text
        assert "Copy the public link" not in r.text and "/cycles/" not in r.text
        assert 'href="/c/tlphone#demos"' in r.text
        r = await visitor.get("/demos/rep-1/play")
        assert r.status_code == 303 and r.headers["location"].endswith("/demos/rep-1")

    async def test_another_customer_s_demo_is_refused(self, app, owner, visitor):
        await _nadia(owner, visitor)
        await app.state.report_repo.save(_report("rep-2", project_id="jrechet/yakoi"))
        r = await visitor.get("/demos/rep-2", headers=HTML)
        assert r.status_code == 403 and 'data-testid="refused"' in r.text
        r = await visitor.get("/demos/nothing", headers=HTML)
        assert r.status_code == 404

    async def test_the_owner_still_sees_everything(self, app, owner, visitor):
        await _nadia(owner, visitor)
        await app.state.report_repo.save(_report("rep-1"))
        r = await owner.get("/demos/rep-1", headers=HTML)
        assert r.status_code == 200 and "$2.77" in r.text and 'data-testid="visibility"' in r.text
        r = await owner.get("/demos/rep-1?as=member", headers=HTML)
        assert r.status_code == 200 and "$2.77" not in r.text


class TestTheWall:
    async def test_a_member_opens_what_is_theirs_and_nothing_else(self, owner, visitor):
        await _nadia(owner, visitor)
        for path in ("/requests", "/requests/new", "/c/tlphone"):
            r = await visitor.get(path, headers=HTML)
            assert r.status_code == 200, path
        for path in ("/c/tlphone/p/espace-client", "/c/tlphone/p/espace-client/features",
                     "/cycles/abc123abc123", "/settings/customers", "/dashboard", "/r/jrechet/espace-client"):
            r = await visitor.get(path, headers=HTML)
            assert r.status_code == 403, path
        r = await visitor.get("/api/cycles", headers={"accept": "application/json"})
        assert r.status_code == 403

    async def test_a_demo_s_files_are_outside_the_wall_its_listing_is_not(self, visitor):
        r = await visitor.get("/artifacts/cafe1234cafe/walk.webm", headers=HTML)
        assert r.status_code == 404  # no such file, but no door either
        r = await visitor.get("/artifacts/list", headers=HTML)
        assert r.status_code in (303, 401)
