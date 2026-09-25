"""The System role owes no heartbeat once prepare is done.

Seq, 2026-09-25: "Agent 'System' idle for 300s (warning N/3)". prepare sent
one heartbeat ("Checking branch protection…") and never retired the role,
so the watchdog judged it idle for the rest of the cycle.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from theswarm import cycle_graph


def _runtime(github):
    watchdog = MagicMock()
    rt = SimpleNamespace(
        config=SimpleNamespace(is_real_mode=True),
        base_state={"github": github},
        progress=AsyncMock(),
        watchdog=watchdog,
    )
    return SimpleNamespace(context=rt), watchdog


async def test_prepare_retires_the_system_role():
    runtime, watchdog = _runtime(SimpleNamespace(ensure_branch_protection=AsyncMock()))

    await cycle_graph.prepare({}, runtime)

    watchdog.retire.assert_called_once_with("System")


async def test_it_is_retired_even_when_the_check_fails():
    github = SimpleNamespace(ensure_branch_protection=AsyncMock(side_effect=RuntimeError("503")))
    runtime, watchdog = _runtime(github)

    with pytest.raises(RuntimeError):
        await cycle_graph.prepare({}, runtime)

    watchdog.retire.assert_called_once_with("System")
