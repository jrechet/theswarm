"""Dev loop aborts the cycle on ClaudeFatalError instead of retrying.

Prod repro (cycle a6e06fb5b4b7): every Claude call failed with the same
billing 400, yet each dev iteration retried once — burning minutes before
the cycle finally crashed with an opaque error deep in the QA phase.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from theswarm import cycle as cycle_mod
from theswarm.cycle import run_daily_cycle
from theswarm.config import CycleConfig
from theswarm.tools.claude import ClaudeFatalError


def _fatal_graph_factory(counter: dict):
    class _Fatal:
        async def ainvoke(self, _state):
            counter["calls"] += 1
            raise ClaudeFatalError("Anthropic account/billing error: credit balance too low")
    return lambda: _Fatal()


async def test_dev_fatal_error_aborts_cycle_without_retry():
    config = CycleConfig(github_repo="")  # stub mode — no workspace clone
    counter = {"calls": 0}

    with patch.object(cycle_mod, "build_dev_graph", _fatal_graph_factory(counter)):
        with pytest.raises(ClaudeFatalError, match="billing"):
            await run_daily_cycle(config)

    # One invocation, no retry, no further iterations
    assert counter["calls"] == 1


async def test_dev_fatal_error_on_retry_also_aborts():
    """First failure is generic (retry allowed), the retry hits the fatal error."""
    config = CycleConfig(github_repo="")
    counter = {"calls": 0}

    class _GenericThenFatal:
        async def ainvoke(self, _state):
            counter["calls"] += 1
            if counter["calls"] == 1:
                raise RuntimeError("transient network blip")
            raise ClaudeFatalError("Anthropic account/billing error: credit balance too low")

    with patch.object(cycle_mod, "build_dev_graph", lambda: _GenericThenFatal()):
        with pytest.raises(ClaudeFatalError):
            await run_daily_cycle(config)

    assert counter["calls"] == 2
