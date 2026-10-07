"""V3, M4 — the cycle: the theater at /cycles/{id} (docs/plans/2026-10-v3-one-product.md).

The stepper from the phases the cycle announced, the four agents, what
happened, the feature piece by piece, its pull requests, the demo at the
end; `/c/{id}` (V2's address) redirects here; a row nothing runs any more
is drawn from the database and says so.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus, PhaseStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.routes import theater as mod
from theswarm.presentation.web.sse import SSEHub

REPO = "jrechet/espace-client"
HTML = {"accept": "text/html"}
NOW = datetime(2026, 10, 7, 11, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from theswarm.api import get_cycle_tracker
    from theswarm.application.services import progress_bridge

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    tracker._cycles.clear()
    history = dict(progress_bridge._PHASE_HISTORY)
    progress_bridge._PHASE_HISTORY.clear()
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)
    progress_bridge._PHASE_HISTORY.clear()
    progress_bridge._PHASE_HISTORY.update(history)


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


def _live(tracker, issue: int = 85):
    from theswarm.api import CycleRequest, CycleStatus as TrackerStatus

    record = tracker.create(CycleRequest(repo=REPO, issue_number=issue, description=f"Play on issue #{issue}"))
    tracker.update_status(record.id, TrackerStatus.RUNNING)
    return record


async def _row(app, cycle_id: str, status=CycleStatus.COMPLETED, issue: int = 85, phases=()):
    project = next(p for p in await app.state.project_repo.list_all() if str(p.repo) == REPO)
    await app.state.cycle_repo.save(Cycle(
        id=CycleId(cycle_id), project_id=project.id, status=status, triggered_by="web",
        started_at=NOW, completed_at=NOW.replace(hour=11, minute=44) if status != CycleStatus.RUNNING else None,
        total_cost_usd=2.14, prs_opened=(89,), prs_merged=(89,) if status == CycleStatus.COMPLETED else (),
        issue_number=issue, phases=tuple(phases),
    ))


# ── The pieces ───────────────────────────────────────────────────────


class TestTheStepper:
    def test_announced_phases_become_steps_with_their_time(self):
        history = [{"phase": "prepare", "ts": 1000}, {"phase": "po_morning", "ts": 1041},
                   {"phase": "techlead_breakdown", "ts": 1231}, {"phase": "dev_loop", "ts": 1473},
                   {"phase": "dev_iter", "ts": 1473}, {"phase": "techlead_review", "ts": 2468},
                   {"phase": "dev_iter", "ts": 2846}]
        steps = mod.steps_from_history(history, "running", now=4410)
        labels = [(s["label"], s["state"], s["time"]) for s in steps]
        assert labels[:3] == [("Prepare", "done", "0:41"), ("Plan", "done", "3:10"), ("Breakdown", "done", "4:02")]
        assert labels[3] == ("Dev · 1", "done", "16:35") and labels[4] == ("Review", "done", "6:18")
        assert labels[5] == ("Dev · 2", "live", "26:04 …")
        assert [s["label"] for s in steps[6:]] == ["Review", "QA", "Report"]
        assert all(s["state"] == "todo" for s in steps[6:])

    def test_a_finished_cycle_has_no_todo_and_a_failed_one_marks_its_last_step(self):
        history = [{"phase": "po_morning", "ts": 10}, {"phase": "qa", "ts": 70}]
        done = mod.steps_from_history(history, "completed", now=130)
        assert [s["state"] for s in done] == ["done", "done"] and done[-1]["time"] == "1:00"
        failed = mod.steps_from_history(history, "failed", now=130)
        assert [s["state"] for s in failed] == ["done", "failed"]

    def test_the_row_s_phases_stand_in_after_a_restart(self):
        from types import SimpleNamespace

        cycle = SimpleNamespace(
            status=CycleStatus.COMPLETED, completed_at=NOW.replace(minute=30),
            phases=(PhaseExecution(phase="po_morning", agent="po", started_at=NOW, status=PhaseStatus.COMPLETED),
                    PhaseExecution(phase="qa", agent="qa", started_at=NOW.replace(minute=10), status=PhaseStatus.COMPLETED)),
        )
        steps = mod.steps_from_row(cycle)
        assert [(s["label"], s["time"]) for s in steps] == [("Plan", "10:00"), ("QA", "20:00")]

    def test_pull_requests_are_read_off_the_feed(self):
        feed = [
            {"kind": "pr_opened", "text": "PR #89 opened: Reject malformed JSON with 400 (#86)"},
            {"kind": "review", "text": "Review of PR #89: changes requested"},
            {"kind": "step", "text": "Dev iteration 2 started"},
        ]
        prs = mod.prs_from_feed(feed, REPO)
        assert [p["number"] for p in prs] == [86, 89]
        assert prs[1]["text"].startswith("Review of PR #89") and prs[1]["href"].endswith("/pull/89")


# ── The page ─────────────────────────────────────────────────────────


class TestThePage:
    async def test_a_running_cycle_is_drawn_live(self, web, _isolate):
        from theswarm.application.services.progress_bridge import record_phase

        client, app = web
        record = _live(_isolate)
        for phase in ("prepare", "po_morning", "techlead_breakdown", "dev_iter"):
            record_phase(record.id, phase)
        r = await client.get(f"/cycles/{record.id}", headers=HTML)
        assert r.status_code == 200
        assert f'data-testid="theater" data-cycle="{record.id}"' in r.text
        assert 'data-testid="cycle-status"' in r.text and 'data-kind="running"' in r.text
        assert 'data-testid="stepper"' in r.text and 'data-step="dev_iter" data-state="live"' in r.text
        assert 'data-step="qa" data-state="todo"' in r.text
        assert 'data-testid="agent-rail"' in r.text and 'data-testid="pull-requests"' in r.text
        assert "TLphone" in r.text and "/swarm/c/tlphone/p/espace-client" in r.text
        assert f'"/swarm/cycles/{record.id}/stage"' in r.text  # the page polls its stage
        assert "/swarm/api/cycle/" in r.text and "Cancel" in r.text

    async def test_the_stage_answers_for_the_poll(self, web, _isolate):
        client, app = web
        record = _live(_isolate)
        r = await client.get(f"/cycles/{record.id}/stage", headers=HTML)
        assert r.status_code == 200 and 'id="stage-inner" data-status="running"' in r.text

    async def test_the_v2_address_redirects_here(self, web, _isolate):
        client, app = web
        record = _live(_isolate)
        r = await client.get(f"/c/{record.id}", headers=HTML)
        assert r.status_code == 303 and r.headers["location"] == f"/swarm/cycles/{record.id}"
        r = await client.get("/c/nobody", headers=HTML)
        assert r.status_code == 404

    async def test_an_unknown_cycle_is_404(self, web):
        client, app = web
        assert (await client.get("/cycles/does-not-exist", headers=HTML)).status_code == 404

    async def test_a_finished_cycle_is_drawn_from_its_row_and_ends_on_the_demo(self, web):
        client, app = web
        await _row(app, "cafe1234cafe", phases=(
            PhaseExecution(phase="po_morning", agent="po", started_at=NOW, status=PhaseStatus.COMPLETED),
            PhaseExecution(phase="qa", agent="qa", started_at=NOW.replace(minute=20), status=PhaseStatus.COMPLETED),
        ))
        await app.state.report_repo.save(DemoReport(
            id="rep-1", cycle_id=CycleId("cafe1234cafe"), project_id=REPO, created_at=NOW,
            summary=ReportSummary(stories_completed=1, stories_total=1, prs_merged=1, cost_usd=2.14),
        ))
        r = await client.get("/cycles/cafe1234cafe", headers=HTML)
        assert r.status_code == 200
        assert 'data-kind="verified"' in r.text and ">Completed<" in r.text
        assert 'data-testid="stage-demo"' in r.text and 'href="/swarm/demos/rep-1"' in r.text
        assert 'data-step="qa" data-state="done"' in r.text and "$2.14" in r.text

    async def test_a_row_nothing_runs_any_more_is_drawn_and_said(self, web):
        client, app = web
        await _row(app, "dead1234dead", status=CycleStatus.RUNNING)
        r = await client.get("/cycles/dead1234dead", headers=HTML)
        assert r.status_code == 200 and 'data-testid="orphan"' in r.text

    async def test_a_member_is_refused(self, web, _isolate, monkeypatch):
        from theswarm.presentation.web.auth import SESSION_COOKIE, member_subject, mint_session

        monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
        monkeypatch.setenv("SWARM_SESSION_SECRET", "s" * 32)
        client, app = web
        record = _live(_isolate)
        tl = await app.state.customer_service.by_slug("tlphone")
        member, token = await app.state.customer_service.invite(tl, "nadia@tlphone.fr")
        await app.state.customer_service.accept(token)
        client.cookies.set(SESSION_COOKIE, mint_session(member_subject(member.id)))
        r = await client.get(f"/cycles/{record.id}", headers=HTML)
        assert r.status_code == 403
