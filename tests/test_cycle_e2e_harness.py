"""Unit tests for the standalone cycle_e2e.py harness script.

The script lives in scripts/ (not a package), so it's loaded by file path
rather than imported normally.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "cycle_e2e", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cycle_e2e.py"
)
cycle_e2e = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cycle_e2e)


def test_is_regression_true_when_previous_passed_and_current_failed():
    previous = {"repo": "acme/app", "passed": True}
    current = {"repo": "acme/app", "passed": False}

    assert cycle_e2e.is_regression(previous, current) is True


def test_is_regression_false_when_previous_is_none():
    current = {"repo": "acme/app", "passed": False}

    assert cycle_e2e.is_regression(None, current) is False


def test_is_regression_false_when_previous_already_failed():
    previous = {"repo": "acme/app", "passed": False}
    current = {"repo": "acme/app", "passed": False}

    assert cycle_e2e.is_regression(previous, current) is False


def test_read_last_result_returns_most_recent_entry_for_matching_repo_only(tmp_path):
    history = tmp_path / "harness-runs.jsonl"
    entries = [
        {"repo": "acme/app", "passed": True, "seq": 1},
        {"repo": "other/app", "passed": True, "seq": 2},
        {"repo": "acme/app", "passed": False, "seq": 3},
        {"repo": "other/app", "passed": False, "seq": 4},
    ]
    history.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    result = cycle_e2e.read_last_result(history, "acme/app")

    assert result == {"repo": "acme/app", "passed": False, "seq": 3}


def test_read_last_result_returns_none_when_history_file_is_absent(tmp_path):
    history = tmp_path / "does-not-exist.jsonl"

    assert cycle_e2e.read_last_result(history, "acme/app") is None


def test_read_last_result_ignores_unparseable_lines(tmp_path):
    history = tmp_path / "harness-runs.jsonl"
    history.write_text(
        "not json\n" + json.dumps({"repo": "acme/app", "passed": True}) + "\n"
    )

    result = cycle_e2e.read_last_result(history, "acme/app")

    assert result == {"repo": "acme/app", "passed": True}


def test_read_last_result_returns_none_when_no_lines_match_repo(tmp_path):
    history = tmp_path / "harness-runs.jsonl"
    history.write_text(json.dumps({"repo": "other/app", "passed": True}) + "\n")

    assert cycle_e2e.read_last_result(history, "acme/app") is None


# ── V2 M6: the harness scores, and reads the manifest ──────────────


def test_ci_verdict_reads_gh_checks_output():
    assert cycle_e2e.ci_verdict("") == "none"
    assert cycle_e2e.ci_verdict("tests\tpass\t1m") == "green"
    assert cycle_e2e.ci_verdict("tests\tfail\t1m\nlint\tpass") == "RED"


def test_duration_seconds_between_iso_timestamps():
    assert cycle_e2e.duration_seconds("2026-09-23T07:00:00+00:00", "2026-09-23T07:31:00+00:00") == 1860.0
    assert cycle_e2e.duration_seconds("2026-09-23T07:00:00Z", "2026-09-23T07:00:30Z") == 30.0
    assert cycle_e2e.duration_seconds("", "2026-09-23T07:00:30Z") == 0.0
    assert cycle_e2e.duration_seconds("garbage", "also") == 0.0


def test_review_decisions_are_read_off_the_cycle_result():
    assert cycle_e2e.review_decisions({"reviews": [{"decision": "APPROVE"}, {"decision": "COMMENT"}]}) == ["APPROVE", "COMMENT"]
    assert cycle_e2e.review_decisions({}) == []


async def test_the_alert_is_a_no_op_without_a_token(monkeypatch):
    monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
    monkeypatch.setenv("MATTERMOST_URL", "https://chat.example")
    assert await cycle_e2e.alert_mattermost("x") is False


def test_run_one_scores_and_appends_a_full_record(tmp_path, monkeypatch):
    """The whole flow with the network stubbed: what lands in the history."""
    from theswarm import evals

    calls: list[str] = []

    def fake_gh(*args):
        calls.append(" ".join(args))
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/r/issues/41"
        if args[:2] == ("pr", "list"):
            return "[]" if not any("after" in c for c in calls) else "[]"
        if args[:2] == ("issue", "list"):
            return "[]"
        if args[:2] == ("pr", "checks"):
            return "tests\tpass\t1m"
        if args[:2] == ("pr", "view") and "files" in args:
            return "src/app.py\ntemplates/x.html\n"
        if args[:2] == ("pr", "view"):
            return "MERGED"
        return ""

    seen_prs = iter([set(), {77}])
    monkeypatch.setattr(cycle_e2e, "_gh", fake_gh)
    monkeypatch.setattr(cycle_e2e, "wait_for_health", lambda *a, **k: True)  # no network in the suite
    monkeypatch.setattr(cycle_e2e, "prs_before", lambda repo: next(seen_prs))
    monkeypatch.setattr(cycle_e2e, "start_cycle", lambda repo, issue: "cyc-1")
    monkeypatch.setattr(cycle_e2e, "wait_for", lambda cycle_id, budget: ("completed", "po_evening"))
    monkeypatch.setattr(cycle_e2e, "cycle_record", lambda cycle_id: {
        "started_at": "2026-09-23T07:00:00+00:00", "completed_at": "2026-09-23T07:25:00+00:00",
        "result": {"cost_usd": 3.25, "backend": "sdk", "reviews": [{"decision": "APPROVE"}]},
    })
    feature = evals.Feature(id="f1", text="Do it", expected_paths=("**/*.py", "**/*.html"),
                            max_cost_usd=5, max_duration_s=1800)
    history = tmp_path / "runs.jsonl"

    passed, record = cycle_e2e.run_one("o/r", "Do it", feature, 60, history)

    assert passed is True
    assert record["prs"] == [77] and record["feature"] == "f1"
    assert record["ci"] == "green" and record["review_decisions"] == ["APPROVE"]
    assert record["cost_usd"] == 3.25 and record["duration_s"] == 1500
    assert record["within_cost"] is True and record["within_time"] is True
    assert record["files_match"] is True and record["backend"] == "sdk"
    assert record["regression"] is False and record["cycle_id"] == "cyc-1"
    (line,) = history.read_text().splitlines()
    assert json.loads(line)["repo"] == "o/r"


def test_the_harness_waits_out_a_deploy_before_creating_anything():
    """Run 35873827304 hit the rollout window: it created its issue, then the
    cycle start read a 404 page as JSON and failed. Health first."""
    answers = iter([(404, {}), (404, {}), (200, {"status": "ok"})])
    slept: list[float] = []
    ok = cycle_e2e.wait_for_health(budget_s=60, api=lambda path: next(answers), sleep=slept.append)
    assert ok is True
    assert slept == [10, 10]


def test_the_health_wait_gives_up_within_its_budget(monkeypatch):
    clock = iter([0.0, 0.0, 5.0, 11.0, 20.0, 31.0])
    monkeypatch.setattr(cycle_e2e.time, "time", lambda: next(clock))
    ok = cycle_e2e.wait_for_health(budget_s=10, api=lambda path: (404, {}), sleep=lambda s: None)
    assert ok is False
