"""Guards exposed by pinning a cycle to one issue (prod cycle 89c42c25875a).

Targeting made three latent bugs permanent, because every iteration now
derives the same branch name and re-picks the same task instead of drifting
to a different issue:

1. `create_branch` used `checkout -b`, which fails rc=128 once the branch
   exists — iterations 2..5 all died there.
2. `_should_open_pr` existed but was never wired into the graph, so a task
   that committed nothing still tried to open a PR: GitHub 422 "No commits
   between main and …".
3. The dev loop re-picked a task that produced nothing, five times over.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from theswarm import cycle as cycle_mod
from theswarm.agents.dev import _should_open_pr, build_dev_graph
from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle
from theswarm.tools.git import create_branch


@pytest.fixture()
def mock_subprocess(mocker):
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))
    mocker.patch("asyncio.create_subprocess_exec", return_value=proc)
    return proc


# ── 1. Branch creation is idempotent ───────────────────────────────────


async def test_create_branch_resets_instead_of_failing(mock_subprocess):
    await create_branch("/tmp/repo", "feat/issue-173-x")

    branch_call = [
        c.args for c in asyncio.create_subprocess_exec.call_args_list
        if "checkout" in c.args
    ][-1]
    # -B creates or resets; -b fails rc=128 when the branch already exists
    assert "-B" in branch_call
    assert "-b" not in branch_call
    assert branch_call[-1] == "feat/issue-173-x"


# ── 2. No commits → no PR attempt ──────────────────────────────────────


def test_should_open_pr_requires_a_branch_and_a_diff():
    assert _should_open_pr({"branch": "feat/x", "diff_stat": " f.py | 2 +-"}) == "open_pr"
    assert _should_open_pr({"branch": "feat/x", "diff_stat": ""}) == "end"
    assert _should_open_pr({"branch": None, "diff_stat": "x"}) == "end"
    assert _should_open_pr({}) == "end"


def test_graph_routes_through_the_open_pr_guard():
    """The guard must sit between the Ralph Loop and open_pr, not be dead code."""
    drawn = build_dev_graph().get_graph()
    edges = {(e.source, e.target) for e in drawn.edges}

    assert "check_pr" in set(drawn.nodes), "routing node missing — open_pr runs unguarded"
    assert ("quality_gates", "open_pr") not in edges
    assert ("check_pr", "open_pr") in edges


# ── 3. The dev loop stops re-picking a task that yields nothing ─────────


def _graph_returning(states: list[dict]):
    """Dev graph stub yielding one state per iteration."""
    calls = {"n": 0}

    class _Stub:
        async def ainvoke(self, _state):
            index = min(calls["n"], len(states) - 1)
            calls["n"] += 1
            return states[index]

    return lambda: _Stub(), calls


async def test_loop_stops_after_the_same_task_yields_nothing_twice():
    """Pinned cycles would otherwise burn all five iterations on one issue."""
    factory, calls = _graph_returning([{"task": {"number": 173}}])  # never a PR

    with patch.object(cycle_mod, "build_dev_graph", factory):
        await run_daily_cycle(CycleConfig(github_repo=""))

    assert calls["n"] == 2, "expected one retry then a stop, not five iterations"


async def test_loop_keeps_going_while_tasks_differ():
    """Distinct tasks producing no PR are not a stall — keep draining."""
    factory, calls = _graph_returning([
        {"task": {"number": 1}},
        {"task": {"number": 2}},
        {"task": {"number": 3}},
        {"task": None},  # backlog exhausted
    ])

    with patch.object(cycle_mod, "build_dev_graph", factory):
        await run_daily_cycle(CycleConfig(github_repo=""))

    assert calls["n"] == 4


async def test_loop_is_unaffected_when_prs_are_produced():
    factory, calls = _graph_returning([
        {"task": {"number": 1}, "pr": {"number": 10, "url": "u"}},
        {"task": None},
    ])

    with patch.object(cycle_mod, "build_dev_graph", factory):
        result = await run_daily_cycle(CycleConfig(github_repo=""))

    assert calls["n"] == 2
    assert [p["number"] for p in result["prs"]] == [10]
