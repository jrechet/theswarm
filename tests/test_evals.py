"""V2 runtime, M6: the eval manifest, the rotation, the scoring, the trend."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from theswarm import evals
from theswarm.evals import Feature, Observed, feature_of_the_day, files_match, score, trend

MANIFEST = Path("evals/concert-tour-app.yaml")


def test_the_shipped_manifest_loads_and_names_five_features():
    manifest = evals.load_manifest(MANIFEST)
    assert manifest.repo == "jrechet/concert-tour-app"
    assert len(manifest.features) == 5
    assert len({f.id for f in manifest.features}) == 5
    assert manifest.by_id("remaining-tickets").title == "Show the remaining ticket count on each concert card"
    assert evals.manifest_for("jrechet/concert-tour-app") is not None
    assert evals.manifest_for("nobody/nothing") is None


def test_rotation_visits_every_feature_and_is_stable_per_day():
    manifest = evals.load_manifest(MANIFEST)
    seen = {feature_of_the_day(manifest, date(2026, 9, d)).id for d in range(1, 11)}
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
