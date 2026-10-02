"""The player's summary says what QA measured (seen in docs/demos/v2-play-to-demo.webm).

Cycle 28371c2016da's summary slide read "0/0 tests · 0.0 % coverage" one
slide before its gates said 325 unit and 36 E2E tests passed at 97.1 %:
the summary was built from the cycle alone, and QA's gates only reached
the gate list.
"""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.application.services.report_generator import ReportGenerator
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus

GATES = {
    "unit_tests": {"total": 325, "passed": 325, "failed": 0, "status": "pass"},
    "e2e_tests": {"total": 36, "passed": 36, "failed": 0, "status": "pass"},
    "security": {"semgrep_high": 1, "status": "fail"},
    "coverage": {"percent": 97.1, "threshold": 70, "status": "pass"},
}


def _cycle() -> Cycle:
    return Cycle(id=CycleId("28371c2016da"), project_id="jrechet/concert-tour-app",
                 status=CycleStatus.COMPLETED, triggered_by="web",
                 started_at=datetime(2026, 9, 28, 15, 40, tzinfo=timezone.utc))


def test_the_summary_counts_qa_s_tests_and_coverage():
    summary = ReportGenerator().generate(_cycle(), qa_gates=GATES).summary

    assert (summary.tests_passing, summary.tests_total) == (361, 361)
    assert summary.coverage_percent == 97.1
    assert summary.security_critical == 1


def test_a_gate_that_did_not_run_counts_nothing():
    gates = {**GATES, "e2e_tests": {"total": 0, "passed": 0, "status": "not_run"},
             "coverage": {"percent": 0.0, "status": "not_run"}}

    summary = ReportGenerator().generate(_cycle(), qa_gates=gates).summary

    assert (summary.tests_passing, summary.tests_total) == (325, 325)
    assert summary.coverage_percent == 0.0


def test_without_qa_the_summary_is_the_old_one():
    summary = ReportGenerator().generate(_cycle()).summary

    assert (summary.tests_passing, summary.tests_total, summary.coverage_percent) == (0, 0, 0.0)


async def _player(tmp_path, summary, gates=()):
    from httpx import ASGITransport, AsyncClient

    from theswarm.application.events.bus import EventBus
    from theswarm.domain.reporting.entities import DemoReport
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository, SQLiteProjectRepository, init_db,
    )
    from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    conn = await init_db(str(tmp_path / "p.db"))
    reports = SQLiteReportRepository(conn)
    await reports.save(DemoReport(
        id="rpt-1", cycle_id=CycleId("28371c2016da"), project_id="jrechet/concert-tour-app",
        created_at=datetime(2026, 9, 28, tzinfo=timezone.utc), summary=summary,
        quality_gates=tuple(gates),
    ))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
                         EventBus(), SSEHub(), report_repo=reports, db=conn)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            return (await client.get("/demos/rpt-1/play")).text
    finally:
        await conn.close()


async def test_the_player_shows_what_qa_measured(tmp_path):
    summary = ReportGenerator().generate(_cycle(), qa_gates=GATES).summary

    html = await _player(tmp_path, summary)

    assert "361/361" in html and "97.1%" in html


async def test_the_player_says_not_measured_rather_than_zero(tmp_path):
    from theswarm.domain.reporting.entities import ReportSummary

    html = await _player(tmp_path, ReportSummary(stories_completed=1, stories_total=1))

    assert "0/0" not in html and "0.0%" not in html
    assert html.count("not measured") == 2


async def test_the_badge_does_not_claim_gates_that_did_not_run(tmp_path):
    """"All Quality Gates Pass" over four skipped gates is a claim nobody made."""
    from theswarm.domain.reporting.entities import ReportSummary
    from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus

    gates = (QualityGate(name="feature_pages", status=QualityStatus.PASS),
             QualityGate(name="e2e_tests", status=QualityStatus.SKIP),
             QualityGate(name="coverage", status=QualityStatus.SKIP))

    html = await _player(tmp_path, ReportSummary(), gates=gates)

    assert "All Quality Gates Pass" not in html
    assert "No gate failed · 2 not run" in html
