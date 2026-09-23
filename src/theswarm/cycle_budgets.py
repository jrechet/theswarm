"""The cycle's budgets and the exceptions that enforce them.

Shared by the imperative runner (`cycle.py`, which re-exports them so
callers and tests keep importing from there) and the durable graph
(`cycle_graph.py`, V2 runtime M4). The numbers are invariants held by
tests — move a phase, move its test; never the number without proof.
"""

from __future__ import annotations

MAX_DEV_ITERATIONS = 5  # safety cap per cycle

# dev_iter budget: an implementation call runs up to IMPLEMENT_TIMEOUT_SECONDS
# (420s, retried once by ClaudeCLI on a transient failure), a cold dependency
# install up to 300s, pytest 120s, plus up to two Ralph Loop repair rounds.
# The old 8-minute cap was sized for the 180s-per-call era and killed every
# substantial task mid-flight during the endurance run.
PHASE_TIMEOUTS = {
    # Each budget must hold one Claude call plus its grown retry (a retried
    # timeout gets timeout_growth× more room), otherwise the phase timeout
    # fires first and hides the real cause.
    "po_morning": 8 * 60,
    "techlead_breakdown": 10 * 60,
    # 25 min once capped the usable budget below 520s, under what
    # TheSwarm's own repo needs to be read at all; 30 min then stopped
    # fitting when the Dev's test budget went from 120s to QA's 900s, so
    # that the gate could finally measure a real suite instead of always
    # reporting `tests_unavailable`.
    #
    # The binding path is the Ralph one, which runs the tests twice:
    # implementation (600) + install (300) + tests (300) + the Ralph retry
    # (600) + tests again (300) = 2100s. 40 min leaves 300s for the commit
    # and the push. That arithmetic is asserted by
    # tests/test_persisted_timeout_floor.py::TestTheImplementationBudget.
    #
    # It briefly stood at 60 min, when the Dev ran the target's whole suite
    # on QA's 900s budget — correct, and an hour per iteration. Scoping the
    # run to the files the diff touches is what brought it back down;
    # tests/test_dev_iteration_budget.py holds the ceiling so it cannot
    # drift back up unnoticed.
    "dev_iter": 40 * 60,
    # A review may ask for REVIEW_TIMEOUT_CEILING_SECONDS (780s) on a large
    # diff, and one phase reviews every open PR. At 300s the phase timeout
    # fired before the call's own budget ever could: the review could not
    # finish whatever it found, twice on consecutive local cycles and once
    # in prod (5f8f0f63f58c, "the pass that mattered"). #130 cut how many
    # reviews run per phase without reconciling the two numbers. 30 min
    # holds one ceiling-sized review with room to spare, or several
    # ordinary ones — the same budget dev_iter and qa already carry.
    # tests/test_review_budget_fits_its_phase.py keeps the invariant.
    "techlead_review": 30 * 60,
    "qa": 30 * 60,
    "po_evening": 5 * 60,
    "retrospective": 5 * 60,
}


class BudgetExceeded(Exception):
    """Raised when a role exceeds its token budget."""
    def __init__(self, role: str, used: int, budget: int) -> None:
        self.role = role
        self.used = used
        self.budget = budget
        super().__init__(f"{role} exceeded token budget: {used:,} > {budget:,}")


class PhaseTimeout(Exception):
    """Raised when a phase exceeds its hard timeout."""
    def __init__(self, phase: str, timeout: int) -> None:
        self.phase = phase
        self.timeout = timeout
        super().__init__(f"phase {phase!r} exceeded {timeout}s hard timeout")
