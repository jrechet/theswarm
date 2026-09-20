"""A review call must be able to finish inside its own phase.

`_review_timeout` grants up to `REVIEW_TIMEOUT_CEILING_SECONDS` (780s) while
`PHASE_TIMEOUTS["techlead_review"]` capped the phase at 300s. The phase
timeout fires first, always: the review could not finish whatever it found,
and the work already paid for was thrown away.

Seen twice on consecutive local cycles:

    16:24:15  Claude CLI: timeout=780s prompt_chars=10778
    16:29:10  Phase techlead_review exceeded 300s — aborting

and once in production before that — AGENTS.md records cycle 5f8f0f63f58c
timing out "on the pass that mattered". #130 reduced how many reviews a
phase runs; it never reconciled the two budgets.
"""

from __future__ import annotations

from theswarm.agents.techlead import (
    REVIEW_TIMEOUT_CEILING_SECONDS,
    REVIEW_TIMEOUT_FLOOR_SECONDS,
    _review_timeout,
)
from theswarm.cycle import PHASE_TIMEOUTS


def test_the_largest_review_budget_fits_inside_the_phase():
    phase = PHASE_TIMEOUTS["techlead_review"]

    assert REVIEW_TIMEOUT_CEILING_SECONDS <= phase, (
        f"a review may ask for {REVIEW_TIMEOUT_CEILING_SECONDS}s inside a "
        f"{phase}s phase — the phase timeout fires first and the review can "
        "never complete, whatever it finds"
    )


def test_a_real_diff_prompt_fits_too():
    """The 10778-char prompt from the cycle that exposed this."""
    phase = PHASE_TIMEOUTS["techlead_review"]

    assert _review_timeout(10778) <= phase


def test_the_phase_holds_more_than_one_review():
    """A cycle reviews every open PR in one phase; three is ordinary."""
    phase = PHASE_TIMEOUTS["techlead_review"]

    assert phase >= 3 * REVIEW_TIMEOUT_FLOOR_SECONDS, (
        "one phase reviews all open PRs; sizing it for a single floor-budget "
        "review makes the third PR abort the phase"
    )
