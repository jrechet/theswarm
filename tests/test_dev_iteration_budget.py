"""A Dev iteration's phase must hold the work it schedules.

`TEST_RUN_TIMEOUT_SECONDS` was 120s, and its own comment said why: "the
phase budget cannot hold that next to two implementation calls". The
consequence, on this repository, is that the Dev's quality gate never
measured anything — the suite needs about three minutes, so every iteration
reported `tests_unavailable` and deferred to CI. Honest, but blind: the
Ralph Loop can only fix what it can see fail.

Owner's decision (2026-09-20): give the Dev the same budget QA has. That
only works if the phase grows with it, which is what these tests pin.
"""

from __future__ import annotations

from theswarm.agents.dev import TEST_RUN_TIMEOUT_SECONDS
from theswarm.agents.qa import QA_TEST_TIMEOUT_SECONDS


def test_the_dev_gate_can_run_what_qa_runs():
    """Both run the target's whole suite; a smaller cap cannot measure it."""
    assert TEST_RUN_TIMEOUT_SECONDS >= QA_TEST_TIMEOUT_SECONDS, (
        f"the Dev gets {TEST_RUN_TIMEOUT_SECONDS}s for the same suite QA "
        f"gets {QA_TEST_TIMEOUT_SECONDS}s for — it will report "
        "tests_unavailable forever and the Ralph Loop stays blind"
    )


# The phase arithmetic itself is guarded by
# tests/test_persisted_timeout_floor.py::TestTheImplementationBudget, which
# counts the fuller path: implementation, install, tests, the Ralph retry,
# and the tests a second time. Duplicating a weaker version of it here would
# only give the two a way to disagree.
