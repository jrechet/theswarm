"""A phase must outlast the Claude call it wraps, plus that call's retry.

If the phase timeout fires first, the cycle reports "phase timed out" and
the real cause (the model needed more room) is lost.
"""

from __future__ import annotations

from theswarm.agents.po import PLANNING_TIMEOUT_SECONDS
from theswarm.agents.techlead import BREAKDOWN_TIMEOUT_SECONDS
from theswarm.cycle import PHASE_TIMEOUTS
from theswarm.tools.claude import ClaudeCLI

GROWTH = ClaudeCLI.timeout_growth


def _attempt_plus_retry(call_budget: int) -> float:
    return call_budget + call_budget * GROWTH


def test_techlead_breakdown_phase_holds_attempt_and_retry():
    assert _attempt_plus_retry(BREAKDOWN_TIMEOUT_SECONDS) < PHASE_TIMEOUTS["techlead_breakdown"]


def test_po_morning_phase_holds_attempt_and_retry():
    assert _attempt_plus_retry(PLANNING_TIMEOUT_SECONDS) < PHASE_TIMEOUTS["po_morning"]


def test_budgets_are_above_what_actually_timed_out_in_prod():
    """120s was the value that failed twice on cycle 11e5fe09535f."""
    assert BREAKDOWN_TIMEOUT_SECONDS > 120
    assert PLANNING_TIMEOUT_SECONDS > 120
