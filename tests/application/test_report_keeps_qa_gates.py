"""The stored report keeps QA's gates, not only "the cycle completed".

A report is the one record of a cycle that outlives the container: the
tracker's result (QA's gates, the E2E excerpt, coverage) is memory. The
daily run of 2026-09-26 (1418b48f3180) had coverage 96.8% and an E2E
failure; its stored report said one thing — `cycle_completion: pass`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.application.services.report_generator import ReportGenerator
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.reporting.value_objects import QualityStatus

QA_GATES = {
    "unit_tests": {"total": 306, "passed": 306, "failed": 0, "status": "pass", "reason": ""},
    "e2e_tests": {
        "total": 31, "passed": 30, "failed": 1, "status": "fail",
        "failure_excerpt": "E   assert 10 == 20\nFAILED tests/e2e/test_api_e2e.py::test_default_pagination",
        "repaired_from": "", "reason": "",
    },
    "security": {"semgrep_high": 0, "status": "pass"},
    "coverage": {"percent": 96.8, "threshold": 70, "status": "pass", "reason": ""},
}


def _cycle() -> Cycle:
    return Cycle(
        id=CycleId("1418b48f3180"), project_id="jrechet/concert-tour-app",
        status=CycleStatus.COMPLETED, triggered_by="web",
        started_at=datetime(2026, 9, 26, 7, 12, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 26, 7, 36, tzinfo=timezone.utc),
    )


def _gates(report) -> dict:
    return {g.name: g for g in report.quality_gates}


def test_qa_gates_follow_the_completion_gate():
    report = ReportGenerator().generate(_cycle(), qa_gates=QA_GATES)

    names = [g.name for g in report.quality_gates]
    assert names == ["cycle_completion", "unit_tests", "e2e_tests", "security", "coverage"]


def test_each_gate_says_what_it_measured():
    gates = _gates(ReportGenerator().generate(_cycle(), qa_gates=QA_GATES))

    assert gates["unit_tests"].status == QualityStatus.PASS
    assert gates["unit_tests"].detail == "306 passed, 0 failed"
    assert gates["e2e_tests"].status == QualityStatus.FAIL
    assert gates["e2e_tests"].detail.startswith("30 passed, 1 failed — E   assert 10 == 20")
    assert gates["security"].detail == "0 HIGH findings"
    assert gates["coverage"].value == 96.8
    assert gates["coverage"].detail == "96.8% (threshold 70%)"


def test_a_gate_that_did_not_run_is_skipped_with_its_reason():
    gates = _gates(ReportGenerator().generate(_cycle(), qa_gates={
        "coverage": {"percent": 0.0, "threshold": 70, "status": "not_run", "reason": "pytest-cov not installed"},
        "e2e_tests": {"total": 0, "passed": 0, "failed": 0, "status": "not_run",
                      "failure_excerpt": "", "reason": "server exited rc=1"},
    }))

    assert gates["coverage"].status == QualityStatus.SKIP
    assert gates["coverage"].detail == "not run: pytest-cov not installed"
    assert gates["e2e_tests"].detail == "not run: server exited rc=1"


def test_a_repaired_e2e_file_is_said():
    gates = _gates(ReportGenerator().generate(_cycle(), qa_gates={
        "e2e_tests": {"total": 24, "passed": 24, "failed": 0, "status": "pass",
                      "failure_excerpt": "", "repaired_from": "E   fixture 'api_client' not found"},
    }))

    assert gates["e2e_tests"].detail == "24 passed, 0 failed (file repaired once: fixture 'api_client' not found)"


def test_the_repair_is_said_in_one_line():
    """cancel-tour (d119d706fbae): the gates slide carried pytest's whole
    excerpt — a dozen "ERROR at setup of …" blocks — under a passing gate."""
    excerpt = "\n".join([
        "___ ERROR at setup of test_feature_cancel_tour_cancels_all_upcoming_concerts ___",
        "E   TypeError: 'module' object is not callable",
        "___ ERROR at setup of test_feature_cancel_tour_requires_a_reason ___",
        "E   TypeError: 'module' object is not callable",
    ])
    gates = _gates(ReportGenerator().generate(_cycle(), qa_gates={
        "e2e_tests": {"total": 15, "passed": 15, "failed": 0, "status": "pass",
                      "failure_excerpt": "", "repaired_from": excerpt},
    }))

    assert gates["e2e_tests"].detail == (
        "15 passed, 0 failed (file repaired once: TypeError: 'module' object is not callable)")


def test_no_qa_gates_is_the_old_report():
    report = ReportGenerator().generate(_cycle())

    assert [g.name for g in report.quality_gates] == ["cycle_completion"]


def test_an_unknown_gate_or_status_does_not_break_the_report():
    gates = _gates(ReportGenerator().generate(_cycle(), qa_gates={
        "lint": {"status": "weird"}, "coverage": "not a dict",
    }))

    assert gates["lint"].status == QualityStatus.WARN
    assert "coverage" not in gates


async def test_the_cycle_s_report_carries_the_gates(monkeypatch):
    from theswarm import api

    saved = []

    class Repo:
        async def save(self, report):
            saved.append(report)

    class Bus:
        async def publish(self, event):
            pass

    await api._emit_demo_ready(
        event_bus=Bus(), report_repo=Repo(), base_path="", cycle_id="1418b48f3180",
        repo="jrechet/concert-tour-app",
        result={"cost_usd": 1.76, "prs": [], "demo_report": {"quality_gates": QA_GATES}},
    )

    (report,) = saved
    assert "coverage" in {g.name for g in report.quality_gates}
