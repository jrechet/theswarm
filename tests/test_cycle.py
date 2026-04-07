"""Test that the stub cycle runs end-to-end without errors."""

import pytest

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle
from theswarm.token_counter import TokenTracker


async def test_stub_cycle_runs():
    """The full cycle should complete with zero tokens in stub mode."""
    config = CycleConfig(github_repo="", team_id="test")
    result = await run_daily_cycle(config)
    assert result["tokens"] == 0
    assert result["cost_usd"] == 0.0
    assert result["demo_report"] is not None


def test_token_tracker():
    tracker = TokenTracker()
    tracker.record("dev", 100_000, cost_usd=0.30)
    tracker.record("qa", 50_000, cost_usd=0.15)
    assert tracker.total_tokens == 150_000
    assert tracker.total_cost == pytest.approx(0.45, abs=0.01)
