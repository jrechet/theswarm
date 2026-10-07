"""V3, M4 — the demo: the player at /demos/{id} (docs/plans/2026-10-v3-one-product.md).

The verdict read off the behaviour gates, the video, what QA measured,
what was built, who can see it; `/demos/{id}/play` (V1) redirects here;
`/d/{short}` is the public, read-only page outside the wall.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType, QualityGate, QualityStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.routes import player as mod
from theswarm.presentation.web.sse import SSEHub

REPO = "jrechet/espace-client"
HTML = {"accept": "text/html"}
NOW = datetime(2026, 10, 7, 11, 44, tzinfo=timezone.utc)


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
    _, token = await app.state.customer_service.invite(tl, "nadia@tlphone.fr", "Nadia")
    await app.state.customer_service.accept(token)
    project = next(p for p in await app.state.project_repo.list_all() if str(p.repo) == REPO)
    await app.state.cycle_repo.save(Cycle(
        id=CycleId("cafe1234cafe"), project_id=project.id, status=CycleStatus.COMPLETED, triggered_by="web",
        started_at=NOW.replace(hour=11, minute=0), completed_at=NOW, total_cost_usd=2.77,
        prs_opened=(82, 83), prs_merged=(82, 83), issue_number=76,
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    await conn.close()


def _gate(name, status, detail="", value=None):
    return QualityGate(name=name, status=QualityStatus(status), detail=detail, value=value)


def _report(rid="rep-1", *, gates=(), stories=None, when=NOW) -> DemoReport:
    return DemoReport(
        id=rid, cycle_id=CycleId("cafe1234cafe"), project_id=REPO, created_at=when,
        summary=ReportSummary(stories_completed=2, stories_total=2, prs_merged=2, cost_usd=2.77,
                              tests_passing=312, tests_total=312, coverage_percent=91.0),
        stories=tuple(stories if stories is not None else (
            StoryReport(ticket_id="77", title="PDF renderer with the new two-column layout", status="completed",
                        pr_number=82, pr_url=f"https://github.com/{REPO}/pull/82", files_changed=6, lines_added=412, lines_removed=38,
                        screenshots_after=(Artifact(type=ArtifactType("screenshot"), label="feature_pr_82_invoices", path="x/shot.png"),)),
            StoryReport(ticket_id="78", title="Monthly export endpoint", status="completed", pr_number=83),
        )),
        quality_gates=tuple(gates),
        artifacts=(Artifact(type=ArtifactType("screenshot"), label="home", path="x/home.png"),
                   Artifact(type=ArtifactType("video"), label="walk", path="x/walk.webm")),
    )


VERIFIED = (_gate("unit_tests", "pass", "312 passed, 0 failed"), _gate("feature_e2e", "pass", "6 passed, 0 failed"),
            _gate("feature_pages", "pass", "2 × 200"), _gate("security", "pass", "semgrep 0 HIGH · bandit 0 HIGH"),
            _gate("coverage", "pass", "91% (threshold 70%)", 91.0))


class TestTheVerdict:
    def test_read_off_the_behaviour_gates(self):
        assert mod.verdict_of(VERIFIED) == "verified"
        assert mod.verdict_of((_gate("feature_e2e", "fail"), _gate("feature_pages", "pass"))) == "broken"
        assert mod.verdict_of((_gate("unit_tests", "pass"),)) == "unverified"
        assert mod.verdict_of(()) == "unverified"

    def test_gate_rows_carry_their_words(self):
        rows = mod.gate_rows(VERIFIED)
        assert [r["label"] for r in rows] == ["Unit tests", "Feature tests", "Feature pages", "Security", "Coverage"]
        assert rows[1]["kind"] == "ok" and rows[1]["value"] == "6 passed, 0 failed"
        assert rows[4]["value"] == "91% (threshold 70%)"


class TestThePlayer:
    async def test_the_demo_page(self, web):
        client, app = web
        await app.state.report_repo.save(_report(gates=VERIFIED))
        r = await client.get("/demos/rep-1", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="player" data-report="rep-1" data-verdict="verified"' in r.text
        assert "Behaviour verified on the running app" in r.text
        assert "PDF renderer with the new two-column layout + 1 more" in r.text
        assert "#76" in r.text and "44 min" in r.text and "$2.77" in r.text
        assert 'href="/swarm/cycles/cafe1234cafe"' in r.text
        assert 'data-testid="video"' in r.text and "/swarm/artifacts/x/walk.webm" in r.text
        assert r.text.count('data-gate=') == 5 and 'data-gate="feature_e2e" data-status="pass"' in r.text
        assert r.text.count('data-testid="story"') == 2 and "/swarm/artifacts/x/shot.png" in r.text
        assert "PR #82" in r.text and "+412" in r.text
        assert 'data-testid="visibility"' in r.text and "TLphone's 1 member" in r.text
        assert 'data-testid="public-link"' in r.text and "/swarm/d/" in r.text
        assert "TLphone" in r.text and "/swarm/c/tlphone/p/espace-client" in r.text

    async def test_a_broken_build_says_so(self, web):
        client, app = web
        await app.state.report_repo.save(_report(gates=(_gate("feature_calls", "fail", "1 of 3 answered 500"),)))
        r = await client.get("/demos/rep-1", headers=HTML)
        assert 'data-verdict="broken"' in r.text and "the running app says otherwise" in r.text
        assert 'data-gate="feature_calls" data-status="fail"' in r.text

    async def test_earlier_and_later_demos_are_linked(self, web):
        client, app = web
        await app.state.report_repo.save(_report("rep-old", when=NOW.replace(day=1)))
        await app.state.report_repo.save(_report("rep-mid", when=NOW.replace(day=4)))
        await app.state.report_repo.save(_report("rep-new", when=NOW))
        r = await client.get("/demos/rep-mid", headers=HTML)
        assert 'href="/swarm/demos/rep-old"' in r.text and 'href="/swarm/demos/rep-new"' in r.text

    async def test_the_v1_address_redirects_here(self, web):
        client, app = web
        r = await client.get("/demos/rep-1/play", headers=HTML)
        assert r.status_code == 303 and r.headers["location"] == "/swarm/demos/rep-1"

    async def test_an_unknown_demo_is_404(self, web):
        client, app = web
        assert (await client.get("/demos/nothing", headers=HTML)).status_code == 404
        assert (await client.get("/d/deadbeef", headers=HTML)).status_code == 404

    async def test_the_public_page_shows_the_demo_without_the_cost_or_the_links(self, web):
        client, app = web
        report = _report(gates=VERIFIED)
        await app.state.report_repo.save(report)
        r = await client.get(f"/d/{report.public_slug}", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="player"' in r.text and 'data-testid="public-badge"' in r.text
        assert 'data-testid="rail"' not in r.text and 'data-testid="visibility"' not in r.text
        assert "$2.77" not in r.text and "/swarm/cycles/" not in r.text and "PR #82" not in r.text
        assert "Behaviour verified" in r.text and r.text.count('data-testid="story"') == 2
