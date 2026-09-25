"""Parallel Dev sub-tasks in one iteration (V2 runtime, M5b).

`SWARM_DEV_PARALLELISM` > 1: a Dev iteration runs that many Dev graphs at
once, each on its own task and its own worktree. The label flip to
in-progress is not a lock — two pickers could read the same task "ready" —
so the pickers take turns and skip what a sibling claimed. Default 1: the
path every cycle ran before.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from theswarm.agents import dev


class _GitHub:
    """A target issue and its children; yields on every call, like the API."""

    def __init__(self, children: list[int], target_is_task: bool = False):
        self.target = {
            "number": 1, "title": "Feature", "body": "", "state": "open",
            "labels": [{"name": "role:dev"}] if target_is_task else [],
        }
        self.children = [
            {"number": n, "title": f"Task {n}", "body": "Parent: #1", "state": "open",
             "labels": [{"name": "role:dev"}, {"name": "status:ready"}]}
            for n in children
        ]

    async def get_issue(self, number):
        await asyncio.sleep(0)
        return self.target

    async def get_issues(self, labels=None):
        await asyncio.sleep(0)
        return list(self.children)

    async def get_issue_comments(self, number):
        await asyncio.sleep(0)
        return []

    async def add_labels(self, number, labels):
        await asyncio.sleep(0)

    async def remove_label(self, number, label):
        await asyncio.sleep(0)


def _picker_state(github, lock, claimed, attempted):
    return {"github": github, "target_issue": 1, "pick_lock": lock,
            "claimed_tasks": claimed, "attempted_tasks": attempted}


# ── The pickers ────────────────────────────────────────────────────────


async def test_two_pickers_take_two_different_tasks():
    github = _GitHub([11, 12])
    lock, claimed, attempted = asyncio.Lock(), [], []

    a, b = await asyncio.gather(
        dev.pick_task(_picker_state(github, lock, claimed, attempted)),
        dev.pick_task(_picker_state(github, lock, claimed, attempted)),
    )

    assert {a["task"]["number"], b["task"]["number"]} == {11, 12}
    assert sorted(claimed) == [11, 12]


async def test_with_one_task_the_second_picker_takes_nothing():
    github = _GitHub([11])
    lock, claimed, attempted = asyncio.Lock(), [], []

    results = await asyncio.gather(
        dev.pick_task(_picker_state(github, lock, claimed, attempted)),
        dev.pick_task(_picker_state(github, lock, claimed, attempted)),
    )

    assert sorted((r["task"] or {}).get("number", 0) for r in results) == [0, 11]


async def test_a_pinned_task_goes_to_one_picker_only():
    github = _GitHub([], target_is_task=True)
    lock, claimed, attempted = asyncio.Lock(), [], []

    results = await asyncio.gather(
        dev.pick_task(_picker_state(github, lock, claimed, attempted)),
        dev.pick_task(_picker_state(github, lock, claimed, attempted)),
    )

    assert sorted((r["task"] or {}).get("number", 0) for r in results) == [0, 1]


async def test_one_picker_alone_behaves_as_before():
    github = _GitHub([11, 12])

    result = await dev.pick_task({"github": github, "target_issue": 1, "attempted_tasks": []})

    assert result["task"]["number"] in (11, 12)


async def test_the_dev_graph_keeps_the_shared_lock():
    """LangGraph drops input keys the state schema does not declare."""
    from langgraph.graph import END, StateGraph

    from theswarm.config import AgentState

    seen = {}

    async def node(state):
        seen["lock"] = state.get("pick_lock")
        seen["claimed"] = state.get("claimed_tasks")
        return {}

    graph = StateGraph(AgentState)
    graph.add_node("n", node)
    graph.set_entry_point("n")
    graph.add_edge("n", END)
    lock, claimed = asyncio.Lock(), [7]

    await graph.compile().ainvoke({"pick_lock": lock, "claimed_tasks": claimed})

    assert seen["lock"] is lock and seen["claimed"] is claimed


# ── The iteration ──────────────────────────────────────────────────────


def _runtime():
    from theswarm.config import CycleConfig
    from theswarm.cycle_graph import CycleRuntime

    messages: list[str] = []

    async def progress(role, message):
        messages.append(message)

    rt = CycleRuntime(config=CycleConfig(github_repo=""), base_state={}, progress=progress)
    return SimpleNamespace(context=rt), messages


def _graphs(results):
    """A build_dev_graph whose graphs answer `results`, one each, in order."""
    queue = list(results)

    class Graph:
        async def ainvoke(self, state):
            await asyncio.sleep(0)
            answer = queue.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

    return lambda: Graph()


async def test_an_iteration_runs_width_graphs_and_adds_them_up(monkeypatch):
    from theswarm import cycle, cycle_graph

    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "2")
    monkeypatch.setattr(cycle, "build_dev_graph", _graphs([
        {"pr": {"number": 41, "url": "u41"}, "task": {"number": 11}, "tokens_used": 100, "cost_usd": 0.5},
        {"pr": {"number": 42, "url": "u42"}, "task": {"number": 12}, "tokens_used": 50, "cost_usd": 0.25},
    ]))
    runtime, messages = _runtime()

    out = await cycle_graph.dev_iter({"iteration": 0}, runtime)

    assert out["dev_outcome"] == "review"
    assert [p["number"] for p in out["prs"]] == [41, 42]
    assert out["total_cost"] == pytest.approx(0.75)
    assert out["role_tokens"]["dev"] == 150
    assert "Up to 2 tasks side by side" in messages


async def test_a_failed_branch_is_its_tasks_failure_not_the_iterations(monkeypatch):
    from theswarm import cycle, cycle_graph

    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "2")
    monkeypatch.setattr(cycle, "build_dev_graph", _graphs([
        RuntimeError("git exploded"),
        {"pr": {"number": 42, "url": "u42"}, "task": {"number": 12}, "tokens_used": 50, "cost_usd": 0.25},
    ]))
    runtime, messages = _runtime()

    out = await cycle_graph.dev_iter({"iteration": 0}, runtime)

    assert out["dev_outcome"] == "review"
    assert [p["number"] for p in out["prs"]] == [42]
    assert any("A task failed (RuntimeError: git exploded)" in m for m in messages)


async def test_no_task_left_for_anyone_ends_the_loop(monkeypatch):
    from theswarm import cycle, cycle_graph

    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "2")
    monkeypatch.setattr(cycle, "build_dev_graph", _graphs([
        {"task": None, "tokens_used": 0}, {"task": None, "tokens_used": 0},
    ]))
    runtime, _ = _runtime()

    out = await cycle_graph.dev_iter({"iteration": 0}, runtime)

    assert out["dev_outcome"] == "end"


async def test_every_branch_failing_skips_to_the_next_iteration(monkeypatch):
    from theswarm import cycle, cycle_graph

    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "2")
    monkeypatch.setattr(cycle, "build_dev_graph", _graphs([RuntimeError("a"), RuntimeError("b")]))
    runtime, _ = _runtime()

    out = await cycle_graph.dev_iter({"iteration": 0}, runtime)

    assert out["dev_outcome"] == "skip"


async def test_a_quota_still_ends_the_cycle(monkeypatch):
    from theswarm import cycle, cycle_graph
    from theswarm.tools.claude import ClaudeFatalError

    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "2")
    monkeypatch.setattr(cycle, "build_dev_graph", _graphs([
        ClaudeFatalError("Claude subscription exhausted: resets 7pm"),
        {"task": None, "tokens_used": 0},
    ]))
    runtime, _ = _runtime()

    with pytest.raises(ClaudeFatalError):
        await cycle_graph.dev_iter({"iteration": 0}, runtime)


async def test_width_one_keeps_the_single_path(monkeypatch):
    from theswarm import cycle, cycle_graph

    monkeypatch.delenv("SWARM_DEV_PARALLELISM", raising=False)
    built = []

    def build():
        built.append(1)
        return _graphs([{"pr": {"number": 41, "url": "u41"}, "task": {"number": 11},
                         "tokens_used": 1, "cost_usd": 0.0}])()

    monkeypatch.setattr(cycle, "build_dev_graph", build)
    runtime, messages = _runtime()

    out = await cycle_graph.dev_iter({"iteration": 0}, runtime)

    assert built == [1]
    assert out["dev_outcome"] == "review"
    assert not any("side by side" in m for m in messages)


# ── The venvs ──────────────────────────────────────────────────────────


def test_side_by_side_each_worktree_has_its_own_venv(monkeypatch):
    from theswarm.agents.base import venv_home
    from theswarm.tools.git import worktree_path

    root = os.path.join("/ws", "repo")
    task = worktree_path(root, "feat/x")

    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "2")
    assert venv_home(task) == task
    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "1")
    assert venv_home(task) == root


def test_side_by_side_claude_uses_the_worktrees_venv(monkeypatch, tmp_path):
    from theswarm.tools.claude import TARGET_VENV_DIR, _child_env
    from theswarm.tools.git import worktree_path

    task = tmp_path / "repo" / ".worktrees" / "feat--x"
    (task / TARGET_VENV_DIR / "bin").mkdir(parents=True)
    monkeypatch.setenv("SWARM_DEV_PARALLELISM", "2")

    env = _child_env(workdir=str(task))

    assert env["VIRTUAL_ENV"] == str(task / TARGET_VENV_DIR)
    assert worktree_path(str(tmp_path / "repo"), "feat/x") == str(task)


@pytest.mark.parametrize("raw,expected", [("", 1), ("1", 1), ("2", 2), ("0", 1), ("x", 1)])
def test_the_width_is_read_defensively(monkeypatch, raw, expected):
    from theswarm.tools.git import dev_parallelism

    monkeypatch.setenv("SWARM_DEV_PARALLELISM", raw)
    assert dev_parallelism() == expected
