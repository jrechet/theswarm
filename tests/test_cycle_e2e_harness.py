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


def test_is_regression_false_when_the_current_run_was_already_delivered():
    """Cycle 874f575645f2 printed "REGRESSION" for a feature already merged."""
    previous = {"repo": "acme/app", "passed": True, "outcome": "built"}
    current = {"repo": "acme/app", "passed": False, "outcome": "already_delivered"}

    assert cycle_e2e.is_regression(previous, current) is False


def _no_api(path, payload=None):
    return 0, {"error": "offline"}


def test_past_runs_come_from_the_api_first(tmp_path):
    """The API is the live copy: the checkout's jsonl is main at dispatch,
    stale for a run queued behind another (35908375032)."""
    history = tmp_path / "harness-runs.jsonl"
    history.write_text(json.dumps({"repo": "acme/app", "passed": False, "seq": 0}) + "\n")
    asked: list[str] = []

    def api(path, payload=None):
        asked.append(path)
        return 200, {"runs": [{"repo": "acme/app", "passed": True, "seq": 1}]}

    runs = cycle_e2e.past_runs("acme/app", history, api=api)

    assert runs == [{"repo": "acme/app", "passed": True, "seq": 1}]
    assert asked == ["/api/evals/runs?repo=acme%2Fapp&limit=500"]


@pytest.mark.parametrize("answer", [(0, {"error": "offline"}), (503, {"error": "no database"}), (200, {"runs": []})])
def test_past_runs_fall_back_to_the_file_for_the_repo_only(tmp_path, answer):
    history = tmp_path / "harness-runs.jsonl"
    entries = [
        {"repo": "acme/app", "passed": True, "seq": 1},
        {"repo": "other/app", "passed": True, "seq": 2},
        {"repo": "acme/app", "passed": False, "seq": 3},
    ]
    history.write_text("not json\n" + "\n".join(json.dumps(e) for e in entries) + "\n")

    runs = cycle_e2e.past_runs("acme/app", history, api=lambda path, payload=None: answer)

    assert [r["seq"] for r in runs] == [1, 3]


def test_past_runs_without_api_or_file_are_empty(tmp_path):
    assert cycle_e2e.past_runs("acme/app", tmp_path / "absent.jsonl", api=_no_api) == []


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


async def test_a_failed_alert_names_the_server_that_refused_it(monkeypatch, capsys):
    """Run 35908375032 logged "404 page not found" and nothing else: that is
    Traefik saying no Mattermost container runs behind chat.jrec.fr."""
    import theswarm_common.chat.mattermost as mm

    class _Down:
        def __init__(self, *a, **k):
            pass

        async def connect(self):
            raise RuntimeError("404 page not found\n")

    monkeypatch.setattr(mm, "MattermostAdapter", _Down)
    monkeypatch.setenv("MATTERMOST_URL", "https://chat.example")
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "t")

    assert await cycle_e2e.alert_mattermost("x") is False
    assert "(mattermost alert to https://chat.example failed: 404 page not found)" in capsys.readouterr().out


def test_run_one_scores_and_appends_a_full_record(tmp_path, monkeypatch):
    """The whole flow with the network stubbed: what lands in the history."""
    from theswarm import evals

    monkeypatch.setattr(cycle_e2e, "_api", _no_api)  # post_run and past_runs
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
    monkeypatch.setattr(cycle_e2e, "wait_for", lambda cycle_id, budget: ("completed", "po_evening", cycle_id))
    monkeypatch.setattr(cycle_e2e, "cycle_record", lambda cycle_id: {
        "started_at": "2026-09-23T07:00:00+00:00", "completed_at": "2026-09-23T07:25:00+00:00",
        "result": {"cost_usd": 3.25, "backend": "sdk", "reviews": [{"decision": "APPROVE"}],
                   "demo_report": {"quality_gates": {"e2e_tests": {"status": "fail"}}}},
    })
    feature = evals.Feature(id="f1", text="Do it", expected_paths=("**/*.py", "**/*.html"),
                            max_cost_usd=5, max_duration_s=1800)
    history = tmp_path / "runs.jsonl"

    passed, record = cycle_e2e.run_one("o/r", "Do it", feature, 60, history)

    assert passed is True
    assert record["prs"] == [77] and record["feature"] == "f1"
    # GitHub's own answer, not the cycle's report: #77 reads MERGED.
    assert record["merged"] == [77] and record["unmerged"] == []
    assert record["qa"] == {"e2e_tests": "fail"}
    assert record["ci"] == "green" and record["review_decisions"] == ["APPROVE"]
    assert record["cost_usd"] == 3.25 and record["duration_s"] == 1500
    assert record["within_cost"] is True and record["within_time"] is True
    assert record["files_match"] is True and record["backend"] == "sdk"
    assert record["regression"] is False and record["cycle_id"] == "cyc-1"
    assert record["outcome"] == "built"
    (line,) = history.read_text().splitlines()
    assert json.loads(line)["repo"] == "o/r"


def _stub_a_cycle_with_no_pr(monkeypatch, result: dict, previous_runs: list[dict],
                             closed: tuple[int, ...] = (286, 287, 288)):
    """The 874f575645f2 run: completed, no new PR, nothing left open, the
    breakdown's sub-tasks closed."""
    def fake_gh(*args):
        if args[:2] == ("issue", "create"):
            return "https://github.com/o/r/issues/285"
        if args[:2] == ("issue", "list") and "closed" in args:
            return json.dumps([{"number": n, "body": f"Do a part\n\nParent: #285"} for n in closed]
                              + [{"number": 200, "body": "Parent: #199"}])
        return "[]"

    monkeypatch.setattr(cycle_e2e, "_gh", fake_gh)
    monkeypatch.setattr(cycle_e2e, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(cycle_e2e, "prs_before", lambda repo: {270, 271, 272})
    monkeypatch.setattr(cycle_e2e, "start_cycle", lambda repo, issue: "874f575645f2")
    monkeypatch.setattr(cycle_e2e, "wait_for", lambda cycle_id, budget: ("completed", "po_evening", cycle_id))
    monkeypatch.setattr(cycle_e2e, "cycle_record", lambda cycle_id: {
        "started_at": "2026-09-23T19:18:31+00:00", "completed_at": "2026-09-23T19:28:07+00:00",
        "result": result,
    })
    monkeypatch.setattr(cycle_e2e, "past_runs", lambda repo, history: previous_runs)
    monkeypatch.setattr(cycle_e2e, "post_run", lambda record: True)
    alerts: list[str] = []

    async def alert(text):
        alerts.append(text)
        return True

    monkeypatch.setattr(cycle_e2e, "alert_mattermost", alert)
    return alerts


CITY_SEARCH_BUILT = {"repo": "o/r", "passed": True, "outcome": "built", "feature": "city-search"}


def test_a_feature_already_on_main_is_not_a_failure_nor_a_regression(tmp_path, monkeypatch, capsys):
    from theswarm import evals

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    alerts = _stub_a_cycle_with_no_pr(
        monkeypatch, {"cost_usd": 0.83, "backend": "sdk", "already_satisfied": [286, 287, 288]},
        [CITY_SEARCH_BUILT],
    )
    feature = evals.Feature(id="city-search", text="Add a search box", expected_paths=("**/*.py",))
    history = tmp_path / "runs.jsonl"

    ok, record = cycle_e2e.run_one("o/r", feature.text, feature, 60, history)

    assert ok is True
    assert record["outcome"] == "already_delivered" and record["passed"] is False
    assert record["regression"] is False
    assert record["already_satisfied"] == [286, 287, 288]
    assert alerts == []
    out = capsys.readouterr().out
    assert "NOT MEASURED — already delivered" in out and "#286, #287, #288" in out
    assert "::warning title=E2E harness::o/r [city-search]: already delivered" in out
    assert "REGRESSION" not in out and "FAIL" not in out
    assert json.loads(history.read_text())["outcome"] == "already_delivered"


def test_a_sub_task_closed_by_hand_is_not_already_delivered(tmp_path, monkeypatch, capsys):
    """Three closed as satisfied, a fourth closed some other way: that one
    was never built, and the feature is not on main."""
    from theswarm import evals

    _stub_a_cycle_with_no_pr(
        monkeypatch, {"already_satisfied": [286, 287, 288]}, [CITY_SEARCH_BUILT],
        closed=(286, 287, 288, 289),
    )
    feature = evals.Feature(id="city-search", text="Add a search box")

    ok, record = cycle_e2e.run_one("o/r", feature.text, feature, 60, tmp_path / "runs.jsonl")

    assert ok is False
    assert record["outcome"] == "failed" and record["unfinished"] == [289]
    assert "closed, not built: #289" in capsys.readouterr().out


def test_no_pr_and_no_reason_is_still_a_failure_and_a_regression(tmp_path, monkeypatch, capsys):
    """Without the Dev's already-satisfied answers the verdict stays what it was."""
    from theswarm import evals

    alerts = _stub_a_cycle_with_no_pr(monkeypatch, {"cost_usd": 0.83}, [CITY_SEARCH_BUILT])
    feature = evals.Feature(id="city-search", text="Add a search box")

    ok, record = cycle_e2e.run_one("o/r", feature.text, feature, 60, tmp_path / "runs.jsonl")

    assert ok is False
    assert record["outcome"] == "failed" and record["regression"] is True
    assert "FAIL — no pull request produced" in capsys.readouterr().out
    assert len(alerts) == 1 and "REGRESSION" in alerts[0]


def test_a_regression_is_judged_against_the_last_measured_run(tmp_path, monkeypatch):
    """built, then already delivered, then failed: the failure follows a pass."""
    from theswarm import evals

    delivered = {"repo": "o/r", "passed": False, "outcome": "already_delivered", "feature": "city-search"}
    _stub_a_cycle_with_no_pr(monkeypatch, {}, [CITY_SEARCH_BUILT, delivered])
    feature = evals.Feature(id="chronological-order", text="Sort")

    _, record = cycle_e2e.run_one("o/r", feature.text, feature, 60, tmp_path / "runs.jsonl")

    assert record["regression"] is True


def test_a_bare_dispatch_runs_a_feature_the_target_does_not_have(tmp_path, monkeypatch, capsys):
    from theswarm import evals

    manifest = evals.load_manifest(pathlib.Path("evals/concert-tour-app.yaml"))
    of_the_day = evals.feature_of_the_day(manifest)
    ran: list[str] = []
    monkeypatch.setattr(cycle_e2e, "KEY", "k")
    monkeypatch.setattr(cycle_e2e, "past_runs", lambda repo, history: [
        {"repo": repo, "feature": of_the_day.id, "passed": True, "outcome": "built"},
    ])
    monkeypatch.setattr(cycle_e2e, "run_one", lambda repo, text, feature, budget, history: (ran.append(feature.id) or (True, {})))
    monkeypatch.setattr(cycle_e2e.sys, "argv", ["cycle_e2e.py", "--repo", "jrechet/concert-tour-app",
                                                "--history", str(tmp_path / "runs.jsonl")])

    assert cycle_e2e.main() == 0

    assert ran == [evals.next_feature(manifest, [{"feature": of_the_day.id, "passed": True}]).id]
    assert ran != [of_the_day.id]
    assert f"[{of_the_day.id}] is already on jrechet/concert-tour-app" in capsys.readouterr().out


def test_a_feature_asked_for_by_id_runs_even_when_delivered(tmp_path, monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(cycle_e2e, "KEY", "k")
    monkeypatch.setattr(cycle_e2e, "past_runs", lambda repo, history: [
        {"repo": repo, "feature": "city-search", "passed": True, "outcome": "built"},
    ])
    monkeypatch.setattr(cycle_e2e, "run_one", lambda repo, text, feature, budget, history: (ran.append(feature.id) or (True, {})))
    monkeypatch.setattr(cycle_e2e.sys, "argv", ["cycle_e2e.py", "--repo", "jrechet/concert-tour-app",
                                                "--feature-id", "city-search"])

    assert cycle_e2e.main() == 0
    assert ran == ["city-search"]


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


def test_the_scored_record_is_posted_to_the_api(monkeypatch):
    posted: list[tuple[str, dict]] = []
    monkeypatch.setattr(cycle_e2e, "_api", lambda path, payload=None: (posted.append((path, payload)) or (201, {"id": 7})))
    assert cycle_e2e.post_run({"repo": "o/r", "passed": True}) is True
    assert posted == [("/api/evals/runs", {"repo": "o/r", "passed": True})]


def test_a_refused_post_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(cycle_e2e, "_api", lambda path, payload=None: (503, {"error": "no database"}))
    assert cycle_e2e.post_run({"repo": "o/r"}) is False


def test_an_exhausted_manifest_is_announced(tmp_path, monkeypatch, capsys):
    """Every feature delivered: the run still goes (and scores
    already_delivered), but the summary page says to add features."""
    from theswarm import evals

    manifest = evals.load_manifest(pathlib.Path("evals/concert-tour-app.yaml"))
    monkeypatch.setattr(cycle_e2e, "KEY", "k")
    monkeypatch.setattr(cycle_e2e, "past_runs", lambda repo, history: [
        {"repo": repo, "feature": f.id, "passed": True, "outcome": "built"} for f in manifest.features
    ])
    monkeypatch.setattr(cycle_e2e, "run_one", lambda *a, **kw: (True, {}))
    monkeypatch.setattr(cycle_e2e.sys, "argv", ["cycle_e2e.py", "--repo", "jrechet/concert-tour-app",
                                                "--history", str(tmp_path / "runs.jsonl")])

    assert cycle_e2e.main() == 0

    out = capsys.readouterr().out
    assert "::warning::every feature of evals/concert-tour-app.yaml is already on" in out


@pytest.mark.parametrize("typed,expected", [
    ("chronological-order", "chronological-order"),
    ("Sort the tour dates chronologically with the next concert first", "chronological-order"),
    ("  chronological-order  ", "chronological-order"),
    ("Something nobody declared", None),
])
def test_a_typed_feature_naming_the_manifest_is_scored_as_that_feature(typed, expected):
    from theswarm import evals

    manifest = evals.load_manifest(pathlib.Path("evals/concert-tour-app.yaml"))
    found = cycle_e2e._known_feature(manifest, typed)

    assert (found.id if found else None) == expected


def test_a_dispatch_by_id_runs_the_manifest_text(tmp_path, monkeypatch):
    ran: list[tuple[str, str | None]] = []
    monkeypatch.setattr(cycle_e2e, "KEY", "k")
    monkeypatch.setattr(cycle_e2e, "run_one", lambda repo, text, feature, budget, history: (
        ran.append((text, feature.id if feature else None)) or (True, {})))
    monkeypatch.setattr(cycle_e2e.sys, "argv", ["cycle_e2e.py", "--repo", "jrechet/concert-tour-app",
                                                "--feature", "sold-out-badge",
                                                "--history", str(tmp_path / "runs.jsonl")])

    assert cycle_e2e.main() == 0

    (text, feature_id), = ran
    assert feature_id == "sold-out-badge"
    assert text.startswith('Show a "sold out" badge')
