"""A cycle that stops early gives back what it claimed.

The hand-back ran only at the natural end of the dev loop. A cancelled
cycle — or one that crashed mid-loop — skipped it, and every sub-task it
had claimed stayed `in-progress`. The next cycle found #86, #87 and #88
exactly there, one tier below the one task that kept failing, and re-picked
that task five times (0793e29ce7c7).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle

STUB = {"tokens_used": 0, "cost_usd": 0.0, "result": "ok"}
QA = {**STUB, "demo_report": {"overall_status": "green", "date": "2026-09-15"}}


def _graph(state=None, *, ainvoke=None):
    g = MagicMock()
    g.ainvoke = ainvoke or AsyncMock(return_value=state)
    return g


def _base_state():
    github = MagicMock()
    github.ensure_branch_protection = AsyncMock()
    github.get_open_prs = AsyncMock(return_value=[])
    return {
        "team_id": "t", "github_repo": "owner/repo",
        "github": github, "claude": MagicMock(), "workspace": "/nowhere",
    }


def _patches(dev_graph, requeue):
    return [
        patch("theswarm.cycle.build_po_graph", MagicMock(return_value=_graph(STUB))),
        patch("theswarm.cycle.build_techlead_graph", MagicMock(return_value=_graph(STUB))),
        patch("theswarm.cycle.build_dev_graph", MagicMock(return_value=dev_graph)),
        patch("theswarm.cycle.build_qa_graph", MagicMock(return_value=_graph(QA))),
        patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock),
        patch("theswarm.cycle._pull_latest", new_callable=AsyncMock),
        patch("theswarm.cycle._build_base_state", return_value=_base_state()),
        patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock),
        patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock),
        patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock),
        patch("theswarm.cycle._requeue_unfinished", requeue),
    ]


async def _run_with(dev_graph, requeue, *, cancel_when=None):
    config = CycleConfig(github_repo="owner/repo", target_issue=85)
    patches = _patches(dev_graph, requeue)
    for p in patches:
        p.start()
    try:
        task = asyncio.create_task(run_daily_cycle(config))
        if cancel_when is not None:
            await asyncio.wait_for(cancel_when.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
    finally:
        for p in patches:
            p.stop()


class TestCancelledMidLoop:
    async def test_claimed_tasks_are_handed_back(self):
        in_dev = asyncio.Event()

        async def hang(*_a, **_kw):
            in_dev.set()
            await asyncio.sleep(60)

        requeue = AsyncMock(return_value=[89])

        await _run_with(_graph(ainvoke=hang), requeue, cancel_when=in_dev)

        requeue.assert_awaited_once()

    async def test_the_hand_back_is_scoped_to_this_cycle(self):
        in_dev = asyncio.Event()

        async def hang(*_a, **_kw):
            in_dev.set()
            await asyncio.sleep(60)

        requeue = AsyncMock(return_value=[])

        await _run_with(_graph(ainvoke=hang), requeue, cancel_when=in_dev)

        (config,) = requeue.await_args.args
        assert config.target_issue == 85


class TestCrashedMidLoop:
    async def test_claimed_tasks_are_handed_back(self):
        async def boom(*_a, **_kw):
            raise RuntimeError("workspace vanished")

        requeue = AsyncMock(return_value=[88])
        config = CycleConfig(github_repo="owner/repo", target_issue=85)
        patches = _patches(_graph(ainvoke=boom), requeue)
        for p in patches:
            p.start()
        try:
            # The loop retries once, then skips the iteration and carries on:
            # a crash in the Dev graph is not fatal to the cycle.
            await run_daily_cycle(config)
        finally:
            for p in patches:
                p.stop()

        requeue.assert_awaited_once()


class TestNormalEnd:
    async def test_hands_back_exactly_once(self):
        """The natural end already hands back; the safety net must not do
        it a second time on top."""
        nothing_to_do = {**STUB, "task": None, "pr": None}
        requeue = AsyncMock(return_value=[])

        await _run_with(_graph(nothing_to_do), requeue)

        requeue.assert_awaited_once()

    async def test_a_cycle_cancelled_before_the_dev_loop_hands_nothing_back(self):
        in_po = asyncio.Event()

        async def hang_in_po(*_a, **_kw):
            in_po.set()
            await asyncio.sleep(60)

        requeue = AsyncMock(return_value=[])
        config = CycleConfig(github_repo="owner/repo", target_issue=85)
        patches = _patches(_graph({**STUB, "task": None, "pr": None}), requeue)
        patches[0] = patch("theswarm.cycle.build_po_graph",
                           MagicMock(return_value=_graph(ainvoke=hang_in_po)))
        for p in patches:
            p.start()
        try:
            task = asyncio.create_task(run_daily_cycle(config))
            await asyncio.wait_for(in_po.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            for p in patches:
                p.stop()

        requeue.assert_not_awaited()
