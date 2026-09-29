"""The harness judges the behaviour delivered, not the tickets (#79, M5, #85).

`passed` says a PR came out and no sub-task was left unbuilt: the state of
the tickets. Whether the feature *works* was QA's to say, and nothing read
it back. Two things answer it now: QA's E2E run against the running
target, and the pages the PRs added, walked on that same target — a page
that answers 5xx is a feature that crashes. The eval record carries the
verdict (`behaviour`), and the harness fails a run that was built but
broken.
"""

from __future__ import annotations

import importlib.util
import pathlib
from unittest.mock import AsyncMock, patch

from theswarm import evals
from theswarm.agents import qa
from theswarm.agents.qa_feature_pages import feature_pages_gate
from theswarm.application.services.report_generator import _qa_quality_gates
from theswarm.domain.reporting.value_objects import QualityStatus

_SPEC = importlib.util.spec_from_file_location(
    "cycle_e2e", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cycle_e2e.py"
)
cycle_e2e = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cycle_e2e)

PAGES = [
    ("/api/v1/concerts/1/occupancy", "feature_pr_390_concerts_1_occupancy"),
    ("/api/v1/tours", "feature_pr_391_tours"),
]


# ── QA: the feature pages are a gate ─────────────────────────────────


def test_every_feature_page_answering_is_a_pass():
    gate = feature_pages_gate(PAGES, {"/api/v1/concerts/1/occupancy": 200, "/api/v1/tours": 200})

    assert gate["status"] == "pass"
    assert gate["pages"] == [
        {"path": "/api/v1/concerts/1/occupancy", "status": 200},
        {"path": "/api/v1/tours", "status": 200},
    ]
    assert "2 of 2" in gate["reason"]


def test_a_feature_page_that_crashes_fails_the_gate_and_names_itself():
    gate = feature_pages_gate(PAGES, {"/api/v1/concerts/1/occupancy": 500, "/api/v1/tours": 200})

    assert gate["status"] == "fail"
    assert "/api/v1/concerts/1/occupancy answered 500" in gate["reason"]


def test_a_4xx_is_not_a_crash_a_filled_parameter_may_name_nothing():
    """Path parameters are filled with "1": concert 1 may not exist in the
    demo's database, and a 404 there says nothing about the feature."""
    gate = feature_pages_gate(PAGES, {"/api/v1/concerts/1/occupancy": 404, "/api/v1/tours": 200})

    assert gate["status"] == "pass"
    assert "1 of 2" in gate["reason"]


def test_no_page_answering_2xx_is_not_run():
    gate = feature_pages_gate(PAGES, {"/api/v1/concerts/1/occupancy": 404, "/api/v1/tours": None})

    assert gate["status"] == "not_run"
    assert gate["reason"]


def test_no_feature_page_is_not_run_with_the_reason():
    gate = feature_pages_gate([], {})

    assert gate == {"status": "not_run", "pages": [],
                    "reason": "the PRs add no GET route to walk"}


def test_a_demo_that_never_started_walked_nothing():
    gate = feature_pages_gate(PAGES, {}, launch_error="No module named app")

    assert gate["status"] == "not_run"
    assert "No module named app" in gate["reason"]


async def test_the_screenshot_walk_records_what_each_feature_page_answered(monkeypatch, tmp_path):
    answers = {"": 200, "/api/v1/concerts/1/occupancy": 500, "/api/v1/tours": 200}

    async def status(url):
        return answers[url.removeprefix("http://127.0.0.1:9999")]

    class Recorder:
        async def screenshot(self, url, label):
            return (label, b"png")

        async def close(self):
            pass

    class Proc:
        returncode = None

        def send_signal(self, sig):
            self.returncode = 0

        async def wait(self):
            return 0

    monkeypatch.setattr(qa, "_page_status", status)
    monkeypatch.setattr(qa, "e2e_port", lambda: 9998)
    monkeypatch.setattr(qa, "_find_system_python", lambda ws: "python")
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    monkeypatch.setattr(qa, "_demo_launch", lambda ws, py, port: (["true"], {}))
    monkeypatch.setattr(qa, "_pages_to_capture", lambda ws, extra: [("", "homepage"), *extra])
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", Recorder):
        out = await qa.capture_demo_screenshots(
            {"workspace": str(tmp_path), "claude": object(), "feature_pages": PAGES},
        )

    assert out["feature_page_statuses"] == {
        "/api/v1/concerts/1/occupancy": 500, "/api/v1/tours": 200,
    }
    assert [label for label, _ in out["demo_artifacts"]] == ["homepage", "feature_pr_391_tours"]


async def test_the_report_carries_the_feature_pages_gate():
    state = {
        "workspace": "/ws",
        "feature_pages": PAGES,
        "feature_page_statuses": {"/api/v1/concerts/1/occupancy": 500, "/api/v1/tours": 200},
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "tests_passed": True,
        "e2e_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "e2e_passed": True,
    }
    with patch.object(qa, "_saved_artifacts", AsyncMock(return_value=[])):
        out = await qa.generate_demo_report(state)

    gate = out["demo_report"]["quality_gates"]["feature_pages"]
    assert gate["status"] == "fail"
    (stored,) = [g for g in _qa_quality_gates(out["demo_report"]["quality_gates"])
                 if g.name == "feature_pages"]
    assert stored.status == QualityStatus.FAIL
    assert "answered 500" in stored.detail


def test_the_captures_state_declares_the_statuses():
    """LangGraph drops an undeclared key: the report would never see them."""
    from theswarm.config import AgentState

    assert "feature_page_statuses" in AgentState.__annotations__


# ── The eval: a verdict on behaviour ─────────────────────────────────


def test_qa_of_reads_the_feature_pages_gate():
    report = {"quality_gates": {"e2e_tests": {"status": "pass"},
                                "feature_pages": {"status": "fail"}}}

    assert evals.qa_of(report) == {"e2e_tests": "pass", "feature_pages": "fail"}


def test_behaviour_is_verified_by_both_the_e2e_run_and_the_pages():
    assert evals.behaviour_of({"e2e_tests": "pass", "feature_pages": "pass"}) == "verified"


def test_behaviour_is_broken_when_either_says_the_app_misbehaves():
    """The feature's own E2E tests, or its pages — not the whole-API file's
    guesses about other endpoints (test_feature_e2e_gate.py)."""
    assert evals.behaviour_of({"feature_e2e": "fail", "feature_pages": "pass"}) == "broken"
    assert evals.behaviour_of({"e2e_tests": "pass", "feature_pages": "fail"}) == "broken"
    assert evals.behaviour_of({"e2e_tests": "fail", "feature_pages": "pass"}) == "verified"


def test_behaviour_nobody_checked_is_unverified():
    assert evals.behaviour_of({}) == "unverified"
    assert evals.behaviour_of({"e2e_tests": "pass", "feature_pages": "not_run"}) == "unverified"
    assert evals.behaviour_of({"unit_tests": "fail"}) == "unverified"


def test_the_score_carries_the_behaviour_and_keeps_passed_as_it_was():
    record = evals.score(None, evals.Observed(
        state="completed", prs=(390,), merged=(390,),
        qa={"e2e_tests": "pass", "feature_pages": "fail"},
    ))

    assert record["passed"] is True  # the tickets' verdict, comparable with history
    assert record["behaviour"] == "broken"


def test_a_run_that_built_nothing_has_no_behaviour_to_judge():
    record = evals.score(None, evals.Observed(state="failed", qa={"e2e_tests": "fail"}))

    assert record["behaviour"] == "unverified"


def test_the_trend_counts_broken_and_verified_runs():
    runs = [
        {"passed": True, "outcome": "built", "behaviour": "verified"},
        {"passed": True, "outcome": "built", "behaviour": "broken"},
        {"passed": True, "outcome": "built"},  # a record from before the field
    ]

    summary = evals.trend(runs)

    assert summary["verified"] == 1 and summary["broken"] == 1


# ── The harness: built but broken is a failure ───────────────────────


def _stub_a_built_cycle(monkeypatch, qa_gates: dict, previous: list[dict]):
    def fake_gh(*args):
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/r/issues/389"
        if args[:2] == ("pr", "checks"):
            return "tests\tpass\t1m"
        if args[:2] == ("pr", "view") and "files" in args:
            return "src/routers/concerts.py\n"
        if args[:2] == ("pr", "view"):
            return "MERGED"
        return "[]"

    seen = iter([set(), {390}])
    monkeypatch.setattr(cycle_e2e, "_gh", fake_gh)
    monkeypatch.setattr(cycle_e2e, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(cycle_e2e, "quota_wall_until", lambda: "")
    monkeypatch.setattr(cycle_e2e, "prs_before", lambda repo: next(seen))
    monkeypatch.setattr(cycle_e2e, "start_cycle", lambda repo, issue: "cyc-b")
    monkeypatch.setattr(cycle_e2e, "wait_for", lambda cycle_id, budget: ("completed", "po_evening", cycle_id))
    monkeypatch.setattr(cycle_e2e, "cycle_record", lambda cycle_id: {
        "started_at": "2026-09-28T07:00:00+00:00", "completed_at": "2026-09-28T07:20:00+00:00",
        "result": {"cost_usd": 1.2, "backend": "sdk",
                   "demo_report": {"quality_gates": qa_gates}},
    })
    monkeypatch.setattr(cycle_e2e, "past_runs", lambda repo, history: previous)
    monkeypatch.setattr(cycle_e2e, "post_run", lambda record: True)
    alerts: list[str] = []

    async def alert(text):
        alerts.append(text)
        return True

    monkeypatch.setattr(cycle_e2e, "alert_mattermost", alert)
    return alerts


VERIFIED_BEFORE = [{"repo": "o/r", "passed": True, "outcome": "built", "behaviour": "verified"}]


def test_built_but_broken_fails_the_harness_and_says_why(tmp_path, monkeypatch, capsys):
    alerts = _stub_a_built_cycle(monkeypatch, {
        "e2e_tests": {"status": "pass"},
        "feature_pages": {"status": "fail", "reason": "/api/v1/concerts/1/occupancy answered 500"},
    }, VERIFIED_BEFORE)

    ok, record = cycle_e2e.run_one("o/r", "Occupancy", None, 60, tmp_path / "runs.jsonl")

    out = capsys.readouterr().out
    assert ok is False
    assert record["passed"] is True and record["behaviour"] == "broken"
    assert "FAIL — built, but" in out and "answered 500" in out
    assert record["regression"] is True
    assert alerts and "answered 500" in alerts[0]


def test_built_and_verified_passes_and_says_so(tmp_path, monkeypatch, capsys):
    _stub_a_built_cycle(monkeypatch, {
        "e2e_tests": {"status": "pass"}, "feature_pages": {"status": "pass"},
    }, VERIFIED_BEFORE)

    ok, record = cycle_e2e.run_one("o/r", "Occupancy", None, 60, tmp_path / "runs.jsonl")

    assert ok is True and record["behaviour"] == "verified"
    assert "behaviour verified" in capsys.readouterr().out


def test_built_and_unverified_still_passes_on_the_tickets(tmp_path, monkeypatch, capsys):
    """No E2E ran, no page to walk: nothing contradicts the build. The line
    says the behaviour went unchecked; the run is not failed for it."""
    _stub_a_built_cycle(monkeypatch, {"e2e_tests": {"status": "not_run"}}, VERIFIED_BEFORE)

    ok, record = cycle_e2e.run_one("o/r", "Occupancy", None, 60, tmp_path / "runs.jsonl")

    assert ok is True and record["behaviour"] == "unverified"
    assert "behaviour unverified" in capsys.readouterr().out
    assert record["regression"] is False


def test_broken_after_broken_is_not_a_new_regression():
    previous = {"passed": True, "outcome": "built", "behaviour": "broken"}
    current = {"passed": True, "outcome": "built", "behaviour": "broken"}

    assert cycle_e2e.is_regression(previous, current) is False


def test_a_failed_build_after_a_verified_one_is_still_a_regression():
    assert cycle_e2e.is_regression(VERIFIED_BEFORE[0], {"passed": False, "outcome": "failed"}) is True
