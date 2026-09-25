"""V2 runtime, M6: the eval manifest, the rotation, the scoring, the trend."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from theswarm import evals
from theswarm.evals import Feature, Observed, feature_of_the_day, files_match, score, trend

MANIFEST = Path("evals/concert-tour-app.yaml")


ORIGINAL_FIVE = ("remaining-tickets", "city-search", "chronological-order",
                 "sold-out-badge", "upcoming-json")


def _first_five() -> evals.Manifest:
    """The manifest as it shipped with M6: the date-pinned rotation tests
    below were written against five features, and the shipped file grows."""
    shipped = evals.load_manifest(MANIFEST)
    return evals.Manifest(repo=shipped.repo, features=shipped.features[:5])


def test_the_shipped_manifest_loads_with_unique_features():
    manifest = evals.load_manifest(MANIFEST)
    assert manifest.repo == "jrechet/concert-tour-app"
    assert tuple(f.id for f in manifest.features[:5]) == ORIGINAL_FIVE
    assert len(manifest.features) > 5  # fresh ones after the first five were built
    assert len({f.id for f in manifest.features}) == len(manifest.features)
    assert all(f.text and f.max_cost_usd > 0 for f in manifest.features)
    assert manifest.by_id("remaining-tickets").title == "Show the remaining ticket count on each concert card"
    assert evals.manifest_for("jrechet/concert-tour-app") is not None
    assert evals.manifest_for("nobody/nothing") is None


def test_rotation_visits_every_feature_and_is_stable_per_day():
    manifest = evals.load_manifest(MANIFEST)
    days = range(1, len(manifest.features) + 1)
    seen = {feature_of_the_day(manifest, date(2026, 9, d)).id for d in days}
    assert seen == {f.id for f in manifest.features}
    assert feature_of_the_day(manifest, date(2026, 9, 23)) == feature_of_the_day(manifest, date(2026, 9, 23))


def test_a_manifest_without_features_is_refused(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("repo: a/b\nfeatures: []\n")
    with pytest.raises(ValueError):
        evals.load_manifest(path)


@pytest.mark.parametrize("files,expected,verdict", [
    ((), (), None),
    (("src/a.py",), (), None),
    ((), ("**/*.py",), False),
    (("src/a.py", "templates/x.html"), ("**/*.py", "**/*.html"), True),
    (("src/a.py", "README.md"), ("**/*.py",), False),
])
def test_files_match(files, expected, verdict):
    assert files_match(files, expected) is verdict


def _feature(**kw) -> Feature:
    base = dict(id="f", text="Do it", expected_paths=("**/*.py",), max_cost_usd=5.0, max_duration_s=1800)
    base.update(kw)
    return Feature(**base)


def test_a_green_run_scores_green_on_every_axis():
    record = score(_feature(), Observed(
        state="completed", prs=(12,), ci={12: "green"}, files=("src/a.py",),
        review_decisions=("APPROVE",), cost_usd=3.2, duration_s=1200, backend="sdk",
    ))
    assert record["passed"] is True
    assert record["ci"] == "green"
    assert record["within_cost"] is True and record["within_time"] is True
    assert record["files_match"] is True
    assert record["feature"] == "f" and record["backend"] == "sdk"
    assert record["cost_usd"] == 3.2 and record["duration_s"] == 1200


def test_passed_keeps_its_old_meaning_while_budgets_are_judged_separately():
    record = score(_feature(), Observed(
        state="completed", prs=(12,), ci={12: "RED"}, files=("docs/x.md",),
        cost_usd=9.0, duration_s=4000,
    ))
    assert record["passed"] is True          # completed, a PR, nothing unbuilt
    assert record["within_cost"] is False
    assert record["within_time"] is False
    assert record["files_match"] is False
    assert record["ci"] == "RED"


def test_an_unfinished_breakdown_or_a_lost_cycle_fails():
    assert score(_feature(), Observed(state="completed", prs=(1,), unfinished=(7,)))["passed"] is False
    assert score(_feature(), Observed(state="lost", prs=(1,)))["passed"] is False
    assert score(_feature(), Observed(state="completed"))["passed"] is False


def test_without_a_feature_the_budgets_are_not_judged():
    record = score(None, Observed(state="completed", prs=(1,), cost_usd=99.0))
    assert record["within_cost"] is None and record["within_time"] is None
    assert record["files_match"] is None
    assert record["feature"] == ""


def test_history_reads_old_and_new_lines_and_skips_junk(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(
        '{"repo": "a/b", "passed": true, "state": "completed", "prs": [1], "unfinished": []}\n'
        "not json\n"
        '{"repo": "a/b", "passed": false, "state": "completed", "prs": [2], "unfinished": [3],'
        ' "cost_usd": 4.5, "duration_s": 1500, "backend": "sdk"}\n'
        '{"repo": "other/repo", "passed": true}\n'
    )
    entries = evals.read_history(path, repo="a/b")
    assert [e["passed"] for e in entries] == [True, False]
    summary = trend(entries)
    assert summary["count"] == 2
    assert summary["pass_rate"] == 0.5
    assert summary["avg_cost_usd"] == 4.5
    assert summary["avg_duration_s"] == 1500
    assert summary["by_backend"] == {"unknown": {"runs": 1, "passed": 1}, "sdk": {"runs": 1, "passed": 0}}
    assert summary["last"]["prs"] == [2]


def test_an_empty_history_has_no_trend():
    assert trend([])["pass_rate"] is None
    assert evals.read_history(Path("/nowhere/runs.jsonl")) == []


# ── Already delivered: neither a pass nor a failure ─────────────────


def test_every_sub_task_already_satisfied_is_already_delivered_not_a_failure():
    """Cycle 874f575645f2: the city search was merged by two earlier runs,
    the Dev closed #286-#288 as already satisfied, no PR came out."""
    record = score(_feature(), Observed(
        state="completed", already_satisfied=(286, 287, 288), cost_usd=0.83, duration_s=576,
    ))
    assert record["passed"] is False        # no PR came out: the old meaning holds
    assert record["outcome"] == "already_delivered"
    assert record["already_satisfied"] == [286, 287, 288]
    assert record["files_match"] is None    # nothing written, nothing off-target
    assert record["within_cost"] is True    # the cycle still cost something


def test_a_pr_alongside_satisfied_sub_tasks_is_built():
    record = score(_feature(), Observed(state="completed", prs=(12,), already_satisfied=(9,)))
    assert record["passed"] is True and record["outcome"] == "built"


@pytest.mark.parametrize("observed", [
    Observed(state="completed"),                                            # no PR, no reason
    Observed(state="completed", already_satisfied=(9,), unfinished=(10,)),  # one left unbuilt
    Observed(state="failed", already_satisfied=(9,)),                       # the cycle broke
    Observed(state="timeout", already_satisfied=(9,)),
])
def test_satisfied_sub_tasks_do_not_excuse_a_failure(observed):
    record = score(_feature(), observed)
    assert record["passed"] is False and record["outcome"] == "failed"


def test_records_written_before_the_outcome_field_read_off_passed():
    assert evals.outcome_of({"passed": True}) == "built"
    assert evals.outcome_of({"passed": False}) == "failed"
    assert evals.outcome_of({"passed": False, "outcome": "already_delivered"}) == "already_delivered"
    assert evals.outcome_of({"passed": False, "outcome": "nonsense"}) == "failed"


def test_the_pass_rate_counts_measured_runs_only():
    entries = [
        {"passed": True, "outcome": "built", "backend": "sdk", "cost_usd": 3.0},
        {"passed": False, "outcome": "already_delivered", "backend": "sdk", "cost_usd": 1.0},
        {"passed": False, "backend": "sdk"},  # an old failed record
    ]
    summary = trend(entries)
    assert summary["count"] == 3              # all three are drawn
    assert summary["pass_rate"] == 0.5        # 1 built of 2 measured
    assert summary["by_backend"] == {"sdk": {"runs": 2, "passed": 1}}
    assert summary["already_delivered"] == 1
    assert summary["avg_cost_usd"] == 2.0     # it did cost


def test_a_window_of_already_delivered_runs_measured_nothing():
    summary = trend([{"passed": False, "outcome": "already_delivered"}])
    assert summary["pass_rate"] is None
    assert summary["by_backend"] == {}


def test_the_run_to_compare_with_is_the_last_that_measured_something():
    built = {"passed": True, "outcome": "built", "seq": 1}
    delivered = {"passed": False, "outcome": "already_delivered", "seq": 2}
    assert evals.last_measured([built, delivered]) == built
    assert evals.last_measured([delivered]) is None
    assert evals.last_measured([]) is None


# ── Picking a feature the target does not have yet ─────────────────


SEPT_23 = date(2026, 9, 23)  # day 266: city-search is the feature of the day


def test_a_same_day_redispatch_skips_the_feature_just_built():
    """The fourth dispatch of 2026-09-23 asked for the city search again."""
    manifest = _first_five()
    assert feature_of_the_day(manifest, SEPT_23).id == "city-search"
    runs = [{"feature": "city-search", "passed": True, "outcome": "built"}]

    assert evals.next_feature(manifest, runs, SEPT_23).id == "chronological-order"


def test_the_feature_of_the_day_runs_when_the_target_does_not_have_it():
    manifest = _first_five()
    runs = [{"feature": "chronological-order", "passed": True, "outcome": "built"}]
    assert evals.next_feature(manifest, runs, SEPT_23).id == "city-search"
    assert evals.next_feature(manifest, [], SEPT_23).id == "city-search"


def test_already_delivered_and_old_passing_records_count_as_delivered():
    manifest = _first_five()
    runs = [
        {"feature": "city-search", "passed": True},  # before the outcome field
        {"feature": "chronological-order", "passed": False, "outcome": "already_delivered"},
    ]
    assert evals.next_feature(manifest, runs, SEPT_23).id == "sold-out-badge"


def test_a_feature_that_failed_since_it_was_built_comes_back():
    runs = [
        {"feature": "city-search", "passed": True, "outcome": "built"},
        {"feature": "city-search", "passed": False, "outcome": "failed"},
    ]
    assert evals.delivered_features(runs) == set()


def test_when_the_target_has_every_feature_the_feature_of_the_day_runs():
    manifest = _first_five()
    runs = [{"feature": f.id, "passed": True, "outcome": "built"} for f in manifest.features]
    assert evals.next_feature(manifest, runs, SEPT_23).id == "city-search"


def test_a_manifest_is_exhausted_only_when_every_feature_is_delivered():
    manifest = _first_five()
    built = [{"feature": f.id, "passed": True, "outcome": "built"} for f in manifest.features]

    assert evals.exhausted(manifest, built)
    assert not evals.exhausted(manifest, built[:-1])
    assert not evals.exhausted(manifest, [])


def test_the_score_says_which_prs_merged():
    record = evals.score(None, evals.Observed(state="completed", prs=(325, 326, 327), merged=(326, 327)))

    assert record["passed"] is True  # the M6 meaning is kept
    assert record["merged"] == [326, 327] and record["unmerged"] == [325]


def test_the_trend_counts_runs_that_left_prs_open():
    runs = [
        {"passed": True, "outcome": "built", "prs": [1, 2], "merged": [2], "unmerged": [1]},
        {"passed": True, "outcome": "built", "prs": [3], "merged": [3], "unmerged": []},
        {"passed": True, "outcome": "built", "prs": [4]},  # a record from before the field
    ]

    assert evals.trend(runs)["left_open"] == 1
    assert evals.trend([])["left_open"] == 0


def test_qa_gates_are_read_from_the_demo_report():
    report = {"quality_gates": {
        "unit_tests": {"status": "pass"}, "e2e_tests": {"status": "fail", "failure_excerpt": "E x"},
        "security": {"status": "not_run"}, "coverage": {"status": "pass"}, "extra": {"status": "?"},
    }}

    assert evals.qa_of(report) == {"unit_tests": "pass", "e2e_tests": "fail",
                                   "security": "not_run", "coverage": "pass"}
    assert evals.qa_of(None) == {} and evals.qa_of({}) == {}


def test_the_score_and_the_trend_carry_qa():
    record = evals.score(None, evals.Observed(state="completed", prs=(1,), merged=(1,),
                                              qa={"e2e_tests": "fail"}))
    assert record["qa"] == {"e2e_tests": "fail"}

    runs = [record, {"passed": True, "outcome": "built", "qa": {"e2e_tests": "pass"}},
            {"passed": True, "outcome": "built"}]
    assert evals.trend(runs)["qa_red"] == 1
