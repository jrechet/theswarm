"""The Ralph Loop retry counter must actually increment.

Prod repro (cycle 65ab4b0fdf3e): ``retry_count`` was returned by
``retry_implement`` but absent from the ``AgentState`` TypedDict, so
LangGraph dropped it on every state merge. ``_should_retry`` always read 0
and the dev loop retried forever — the logs show ``retrying (1/2)`` four
times in a row — until the 8-minute phase timeout killed it, burning ~$1
of tokens per iteration.
"""

from __future__ import annotations

from theswarm.agents.dev import _should_retry
from theswarm.config import AgentState


def test_agent_state_declares_retry_fields():
    """Without these keys LangGraph silently discards the counter."""
    annotations = AgentState.__annotations__
    assert "retry_count" in annotations
    assert "max_dev_retries" in annotations


def test_retry_until_budget_then_proceed():
    """The routing must stop retrying once the budget is spent."""
    assert _should_retry({"tests_passed": False, "retry_count": 0, "max_dev_retries": 2}) == "retry"
    assert _should_retry({"tests_passed": False, "retry_count": 1, "max_dev_retries": 2}) == "retry"
    # Budget exhausted — proceed to the PR check instead of looping forever
    assert _should_retry({"tests_passed": False, "retry_count": 2, "max_dev_retries": 2}) == "check_pr"
    assert _should_retry({"tests_passed": False, "retry_count": 9, "max_dev_retries": 2}) == "check_pr"


def test_passing_tests_skip_retries():
    assert _should_retry({"tests_passed": True, "retry_count": 0, "max_dev_retries": 2}) == "check_pr"


def test_zero_retry_budget_never_retries():
    assert _should_retry({"tests_passed": False, "retry_count": 0, "max_dev_retries": 0}) == "check_pr"


async def test_retry_implement_increments_counter():
    """Stub mode still has to advance the counter, or the loop never ends."""
    from theswarm.agents.dev import retry_implement

    state: AgentState = {"retry_count": 1, "task": None, "claude": None, "workspace": None}
    result = await retry_implement(state)
    assert result["retry_count"] == 2


def test_base_state_carries_configured_retry_budget():
    """CycleConfig.max_dev_retries must reach the dev graph."""
    from theswarm.config import CycleConfig
    from theswarm.cycle import _build_base_state

    config = CycleConfig(github_repo="")
    config.max_dev_retries = 4
    assert _build_base_state(config)["max_dev_retries"] == 4
