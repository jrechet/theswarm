"""A Dev iteration must be big enough to do its work and small enough to watch.

Two constraints, from two days of running real cycles on this repository.

*Big enough*: at 120s the Dev's gate never measured anything here — the
suite needs about three minutes, so every iteration reported
`tests_unavailable` and deferred to CI. Honest, but it left the Ralph Loop
blind, and a loop can only fix what it watched fail.

*Small enough*: matching QA's 900s fixed the blindness and cost an hour per
iteration, because the Ralph retry runs the tests a second time — five
iterations would span an afternoon. Owner's call (2026-09-20): scope the run
to the files the diff touches instead.

The lower bound lives in test_persisted_timeout_floor.py, which counts the
full path. This file holds the ceiling, so the budget cannot drift back up
without someone noticing.
"""

from __future__ import annotations

from theswarm.agents.dev import TEST_RUN_TIMEOUT_SECONDS
from theswarm.agents.qa import QA_TEST_TIMEOUT_SECONDS
from theswarm.cycle import PHASE_TIMEOUTS

_CEILING_SECONDS = 45 * 60


def test_an_iteration_cannot_run_for_an_hour():
    phase = PHASE_TIMEOUTS["dev_iter"]

    assert phase <= _CEILING_SECONDS, (
        f"dev_iter is {phase}s: five iterations would span "
        f"{phase * 5 / 3600:.1f} hours. If the work genuinely needs this "
        "much, shrink what the Dev runs before growing the phase"
    )


def test_the_dev_run_is_scoped_not_the_whole_suite():
    """A Dev budget at QA's level means it stopped scoping — the thing that
    made an iteration cost an hour."""
    assert TEST_RUN_TIMEOUT_SECONDS < QA_TEST_TIMEOUT_SECONDS, (
        f"the Dev gets {TEST_RUN_TIMEOUT_SECONDS}s and QA "
        f"{QA_TEST_TIMEOUT_SECONDS}s. The Dev runs only the files its diff "
        "touches; needing QA's budget means it is running QA's suite"
    )
