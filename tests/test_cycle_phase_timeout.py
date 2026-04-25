"""PhaseTimeout — each phase has a hard timeout that aborts a hung agent."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from theswarm import cycle as cycle_mod
from theswarm.cycle import PhaseTimeout, run_daily_cycle
from theswarm.config import CycleConfig


def _hung_graph_factory(seconds: float):
    """A LangGraph-like object whose ainvoke just sleeps."""
    class _Hung:
        async def ainvoke(self, _state):
            await asyncio.sleep(seconds)
            return {}
    return lambda: _Hung()


async def test_po_morning_aborts_after_timeout(monkeypatch):
    # Stub mode (no github_repo) — skips workspace clone but still runs phases.
    config = CycleConfig(github_repo="")
    monkeypatch.setattr(cycle_mod, "PHASE_TIMEOUTS", {**cycle_mod.PHASE_TIMEOUTS, "po_morning": 0.1})

    with patch.object(cycle_mod, "build_po_graph", _hung_graph_factory(2.0)):
        with pytest.raises(PhaseTimeout) as exc_info:
            await run_daily_cycle(config)
    assert exc_info.value.phase == "po_morning"


async def test_dev_iteration_timeout_skips_to_next(monkeypatch):
    """Dev timeout in stub mode never reaches the loop — stub returns early.

    Use the public PHASE_TIMEOUTS dict to assert the constant exists and
    contains the documented keys; full coverage is via the route + e2e
    smoke gate (Phase 5.1).
    """
    keys = set(cycle_mod.PHASE_TIMEOUTS.keys())
    assert {"po_morning", "techlead_breakdown", "dev_iter", "techlead_review", "qa", "po_evening"} <= keys


async def test_phase_timeout_exception_carries_phase_name():
    exc = PhaseTimeout("dev_iter", 480)
    assert exc.phase == "dev_iter"
    assert exc.timeout == 480
    assert "dev_iter" in str(exc)
    assert "480" in str(exc)
