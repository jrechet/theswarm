"""The PO's summary on the pages (docs/plans/2026-10-v3-one-product.md, folded
into the PO): a member reads what was delivered, in plain words, first — on
their feature page, above the player, under the title in their list of demos.
The owner sees whether there is one and can ask the PO again; a member never
can. A demo lands → the writer, subscribed to the bus, writes it once.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.services import pinned_issue
from theswarm.application.services.demo_summary import DemoSummaryWriter
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.events import DemoReady
from theswarm.domain.reporting.summary import SKIPPED, DemoSummary
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.auth import SESSION_COOKIE
from theswarm.presentation.web.sse import SSEHub

KEY = "k-summary-test"
HTML = {"accept": "text/html"}
REPO = "jrechet/espace-client"
FEATURE = "/c/tlphone/p/espace-client/f/42"
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
GOOD = {"headline": "You can now export your invoices as a PDF",
        "body": "A new button on the invoices page gives you a PDF of the month. Accounting can open it straight away."}


@pytest.fixture(autouse=True)
def _wall(monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s" * 32)
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


class _Claude:
    def __init__(self, *drafts):
        self.drafts, self.prompts = list(drafts), []

    async def run(self, prompt, **kw):
        self.prompts.append(prompt)
        return SimpleNamespace(structured=self.drafts.pop(0) if self.drafts else None, text="")


@pytest.fixture()
async def rig(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    bus = EventBus()
    reports = SQLiteReportRepository(conn)
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), bus, SSEHub(), db=conn, report_repo=reports)
    claude = _Claude(GOOD, GOOD)
    # the app's own writer, on a Claude that answers the script: the wiring is what is tested
    assert isinstance(app.state.demo_summary_writer, DemoSummaryWriter)
    with patch("theswarm.tools.claude.ClaudeCLI", return_value=claude):
        yield SimpleNamespace(app=app, bus=bus, reports=reports, summaries=app.state.demo_summary_repo, claude=claude, conn=conn)
    await conn.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture()
async def owner(rig):
    async with _client(rig.app) as client:
        r = await client.post("/login", data={"access_key": KEY})
        assert r.status_code == 303
        yield client


@pytest.fixture()
async def visitor(rig):
    async with _client(rig.app) as client:
        yield client


async def _nadia(owner, visitor) -> None:
    r = await owner.post("/settings/customers", data={"name": "TLphone"})
    assert r.status_code == 303
    r = await owner.post("/settings/customers/tlphone/projects", data={"full_name": REPO})
    assert r.status_code == 303
    r = await owner.post("/settings/customers/tlphone/members", data={"email": "nadia@tlphone.fr", "display_name": "Nadia"})
    link = re.search(r'value="(http://test/invite/[^"]+)"', r.text).group(1).replace("http://test", "")
    r = await visitor.get(link)
    assert r.status_code == 303 and SESSION_COOKIE in visitor.cookies


def _report(rid="rep-1", gates=(("feature_pages", "pass"),)) -> DemoReport:
    return DemoReport(
        id=rid, cycle_id=CycleId("cafe1234cafe"), project_id=REPO, created_at=NOW,
        summary=ReportSummary(stories_completed=1, stories_total=1, prs_merged=1, cost_usd=2.77),
        stories=(StoryReport(ticket_id="42", title="Export invoices as PDF", status="completed", pr_number=82),),
        quality_gates=tuple(QualityGate(name=n, status=QualityStatus(s)) for n, s in gates),
    )


def _github(body="Monthly, for accounting"):
    issue = {"number": 42, "title": "Export invoices as PDF", "body": body, "state": "closed",
             "labels": [{"name": "status:review"}], "html_url": f"https://github.com/{REPO}/issues/42"}
    ctx = patch("theswarm.tools.github.GitHubClient")
    client = ctx.start().return_value
    client.get_issues = AsyncMock(return_value=[issue])
    client.get_issue = AsyncMock(return_value=issue)
    client.get_open_pr_briefs = AsyncMock(return_value=[])
    return ctx


async def _delivered(rig):
    """The cycle on issue 42, completed, its demo stored."""
    await rig.app.state.cycle_repo.save(Cycle(
        id=CycleId("cafe1234cafe"), project_id=REPO, status=CycleStatus.COMPLETED, triggered_by="web",
        started_at=NOW, completed_at=NOW, issue_number=42,
    ))
    await rig.reports.save(_report())


class TestWhatAMemberReads:
    async def test_the_summary_on_the_feature_page_the_player_and_the_list(self, rig, owner, visitor):
        await _nadia(owner, visitor)
        await _delivered(rig)
        await rig.summaries.save(DemoSummary(report_id="rep-1", headline=GOOD["headline"], body=GOOD["body"], created_at=NOW))
        ctx = _github()
        try:
            page = await visitor.get(FEATURE, headers=HTML)
            assert page.status_code == 200
            assert 'data-testid="customer-summary"' in page.text and GOOD["headline"] in page.text and "Accounting can open it" in page.text
            assert page.text.index('data-testid="customer-summary"') < page.text.index("What was asked")
            player = await visitor.get("/demos/rep-1", headers=HTML)
            assert 'data-testid="customer-summary"' in player.text and GOOD["body"] in player.text
            assert page.text.count("$") == 0 and "2.77" not in player.text
            home = await visitor.get("/c/tlphone", headers=HTML)
            assert 'data-testid="member-demo-headline"' in home.text and GOOD["headline"] in home.text
        finally:
            ctx.stop()

    async def test_a_member_never_sees_the_owner_s_strip_nor_can_ask_the_po(self, rig, owner, visitor):
        await _nadia(owner, visitor)
        await _delivered(rig)
        player = await visitor.get("/demos/rep-1", headers=HTML)
        assert 'data-testid="summary-owner"' not in player.text and 'data-testid="summary-write"' not in player.text
        r = await visitor.post("/demos/rep-1/summary", headers=HTML)
        assert r.status_code == 403 and rig.claude.prompts == []
        r = await owner.get("/demos/rep-1?as=member", headers=HTML)
        assert 'data-testid="summary-owner"' not in r.text  # the owner looking as a member sees what the member sees

    async def test_a_skipped_summary_shows_the_member_nothing_and_the_owner_why(self, rig, owner, visitor):
        await _nadia(owner, visitor)
        await _delivered(rig)
        await rig.summaries.save(DemoSummary(report_id="rep-1", status=SKIPPED, reason="RuntimeError: session limit", created_at=NOW))
        ctx = _github()
        try:
            member = await visitor.get(FEATURE, headers=HTML)
            assert 'data-testid="customer-summary"' not in member.text
            home = await visitor.get("/c/tlphone", headers=HTML)
            assert 'data-testid="member-demo-headline"' not in home.text
        finally:
            ctx.stop()
        page = await owner.get("/demos/rep-1", headers=HTML)
        assert 'data-testid="summary-owner" data-state="skipped"' in page.text and "session limit" in page.text
        assert "Ask the PO to write it" in page.text

    async def test_the_public_player_carries_it_too(self, rig, owner):
        await _delivered(rig)
        await rig.summaries.save(DemoSummary(report_id="rep-1", headline=GOOD["headline"], body=GOOD["body"], created_at=NOW))
        slug = _report().public_slug
        async with _client(rig.app) as anonymous:
            r = await anonymous.get(f"/d/{slug}", headers=HTML)
        assert r.status_code == 200 and 'data-testid="customer-summary"' in r.text and 'data-testid="summary-owner"' not in r.text


class TestWhatTheOwnerCanDo:
    async def test_the_strip_the_click_and_the_background_write(self, rig, owner):
        await _delivered(rig)
        page = await owner.get("/demos/rep-1", headers=HTML)
        assert 'data-testid="summary-owner" data-state="none"' in page.text and "Ask the PO to write it" in page.text
        ctx = _github()
        try:
            r = await owner.post("/demos/rep-1/summary", headers=HTML)
            assert r.status_code == 303 and r.headers["location"].endswith("/demos/rep-1")
            task = rig.app.state.demo_summary_writer._writing["rep-1"]
            await task
        finally:
            ctx.stop()
        assert "Monthly, for accounting" in rig.claude.prompts[0]  # the customer's own words, read off the feature's issue
        page = await owner.get("/demos/rep-1", headers=HTML)
        assert 'data-state="written"' in page.text and "Write it again" in page.text and GOOD["headline"] in page.text
        r = await owner.post("/demos/nope/summary", headers=HTML)
        assert r.status_code == 404

    async def test_without_a_writer_there_is_no_strip(self, rig, owner):
        await _delivered(rig)
        rig.app.state.demo_summary_writer = None
        page = await owner.get("/demos/rep-1", headers=HTML)
        assert page.status_code == 200 and 'data-testid="summary-owner"' not in page.text
        r = await owner.post("/demos/rep-1/summary", headers=HTML)
        assert r.status_code == 303  # nothing to ask: back to the player


class TestAtTheMomentADemoLands:
    async def test_the_bus_subscription_writes_it_once(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SWARM_DEMO_SUMMARY", "1")
        conn = await init_db(str(tmp_path / "bus.db"))
        try:
            bus = EventBus()
            reports = SQLiteReportRepository(conn)
            app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), bus, SSEHub(), db=conn, report_repo=reports)
            await reports.save(_report())
            claude = _Claude(GOOD, GOOD)
            ctx = _github()
            try:
                with patch("theswarm.tools.claude.ClaudeCLI", return_value=claude):
                    event = DemoReady(project_id=REPO, report_id="rep-1", issue_number=42)
                    await bus.publish(event)
                    await bus.publish(event)  # a second DemoReady for the same report asks nothing
            finally:
                ctx.stop()
            stored = await app.state.demo_summary_repo.get("rep-1")
            assert stored.is_written and stored.headline == GOOD["headline"]
            assert len(claude.prompts) == 1 and "Monthly, for accounting" in claude.prompts[0]
        finally:
            await conn.close()

    async def test_the_suite_s_default_is_off(self, rig):
        # conftest sets SWARM_DEMO_SUMMARY=0: a DemoReady a test publishes calls no Claude
        await rig.reports.save(_report())
        await rig.bus.publish(DemoReady(project_id=REPO, report_id="rep-1", issue_number=42))
        assert rig.claude.prompts == [] and await rig.summaries.get("rep-1") is None
