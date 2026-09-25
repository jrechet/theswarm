"""A run a restart ended is not a verdict on the swarm.

csv-export on 2026-09-25: the cycle and its continuation were both killed
by deploys, the second in QA, after all three PRs (#348-#350) had merged.
The eval scored a failure and would have called a regression had the last
run passed. A cycle ended by a restart and not continued measured the
deploy, not the product: `interrupted`, drawn and counted apart, never
compared with and never a regression.
"""

from __future__ import annotations

import importlib.util
import pathlib

from theswarm import evals
from theswarm.application.services import cycle_resumer

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESTART = (f"{cycle_resumer.RESTART_REASON}; not resumed — it was already an "
           "automatic resume, and a second interruption needs a person to look")


def _observed(**overrides) -> evals.Observed:
    return evals.Observed(**{"state": "failed", "prs": (348, 349, 350),
                             "merged": (348, 349, 350), **overrides})


def test_a_cycle_a_restart_ended_is_interrupted():
    record = evals.score(None, _observed(error=RESTART))

    assert record["outcome"] == evals.OUTCOME_INTERRUPTED
    assert record["passed"] is False
    assert record["error"] == RESTART


def test_the_prefix_is_the_resumer_s_own_words():
    assert cycle_resumer.RESTART_REASON.startswith(evals.INTERRUPTED_PREFIX)


def test_any_other_failure_is_still_a_failure():
    record = evals.score(None, _observed(error="RuntimeError: phase qa timed out"))

    assert record["outcome"] == evals.OUTCOME_FAILED


def test_a_completed_run_is_judged_on_its_work_whatever_its_error_says():
    record = evals.score(None, _observed(state="completed", error=RESTART))

    assert record["outcome"] == evals.OUTCOME_BUILT


def test_an_interrupted_run_is_not_measured():
    built = {"outcome": evals.OUTCOME_BUILT, "passed": True}
    interrupted = {"outcome": evals.OUTCOME_INTERRUPTED, "passed": False}

    assert evals.outcome_of(interrupted) == evals.OUTCOME_INTERRUPTED
    assert not evals.is_measured(interrupted)
    assert evals.last_measured([built, interrupted]) is built


def test_the_trend_counts_interrupted_runs_apart():
    runs = [
        {"outcome": evals.OUTCOME_BUILT, "passed": True},
        {"outcome": evals.OUTCOME_INTERRUPTED, "passed": False},
        {"outcome": evals.OUTCOME_FAILED, "passed": False},
    ]

    trend = evals.trend(runs)

    assert trend["pass_rate"] == 0.5
    assert trend["interrupted"] == 1
    assert trend["already_delivered"] == 0


def _harness():
    spec = importlib.util.spec_from_file_location("cycle_e2e_interrupted", ROOT / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_interrupted_run_is_never_a_regression():
    harness = _harness()
    previous = {"outcome": evals.OUTCOME_BUILT, "passed": True}

    assert not harness.is_regression(previous, {"outcome": evals.OUTCOME_INTERRUPTED})


def test_the_panel_draws_an_interrupted_run_apart():
    template = (ROOT / "src/theswarm/presentation/web/templates/v2/repo.html").read_text()

    assert "run.outcome == 'interrupted'" in template
    assert "evals.interrupted" in template
