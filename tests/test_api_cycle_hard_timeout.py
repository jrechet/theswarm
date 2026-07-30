"""Whole-cycle hard timeout in run_api_cycle.

Prod repro (cycles 338a005e3cea, d70c60edeca3, a3204c6b1b89, efcacbcda4be):
cycles hung 14–42h with a phase stuck 'running'. Per-phase timeouts don't
cover everything (workspace clone, retrospective, …), so run_api_cycle now
caps the whole cycle and concludes the record with a clear error.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from theswarm import api as api_mod
from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker, run_api_cycle


async def test_hung_cycle_is_concluded_by_hard_timeout(monkeypatch):
    monkeypatch.setattr(api_mod, "CYCLE_HARD_TIMEOUT_SECONDS", 0.1)

    async def hang(*_a, **_kw):
        await asyncio.sleep(30)

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/some-repo"))

    with patch("theswarm.cycle.run_daily_cycle", side_effect=hang):
        await run_api_cycle(
            cycle_id=record.id,
            repo="owner/some-repo",
            description="",
            callback_url="",
            allowed_repos=[],
        )

    final = tracker.get(record.id)
    assert final is not None
    assert final.status == CycleStatus.FAILED
    assert "hard timeout" in (final.error or "")
    assert final.completed_at  # record is concluded, not left running


async def test_fast_cycle_unaffected_by_hard_timeout():
    async def quick(*_a, **_kw):
        return {"date": "2026-07-30", "cost_usd": 0.0, "prs": [], "reviews": []}

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/some-repo"))

    with patch("theswarm.cycle.run_daily_cycle", side_effect=quick):
        await run_api_cycle(
            cycle_id=record.id,
            repo="owner/some-repo",
            description="",
            callback_url="",
            allowed_repos=[],
        )

    final = tracker.get(record.id)
    assert final is not None
    assert final.status == CycleStatus.COMPLETED
