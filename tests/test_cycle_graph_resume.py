"""V2 runtime, M4: a cycle is a durable graph; a dead process resumes it.

The acceptance the plan asks for, at graph level: interrupt between two
nodes, resume on the same thread — every node that finished ran once,
the one that died runs again, the cycle completes with one result.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle
from theswarm.cycle_graph import CYCLE_STATE_SCHEMA_VERSION, CycleNotResumable
from theswarm.domain.cycles.value_objects import PHASE_ROLE

STUB = {"tokens_used": 1, "cost_usd": 0.5}
QA_OK = {**STUB, "demo_report": {"overall_status": "green", "date": "d"}}


class _Counting:
    """A graph builder whose graphs count their invocations and can fail
    the first N times — the crash between two checkpoints."""

    def __init__(self, state: dict, fail_first: int = 0):
        self.state = state
        self.calls = 0
        self.fail_first = fail_first

    def __call__(self):
        graph = MagicMock()

        async def ainvoke(_state):
            self.calls += 1
            if self.calls <= self.fail_first:
                raise RuntimeError("container replaced mid-flight")
            return dict(self.state)

        graph.ainvoke = AsyncMock(side_effect=ainvoke)
        return graph


def _base_state(tmp_path) -> dict:
    github = MagicMock()
    github.ensure_branch_protection = AsyncMock()
    github.get_open_prs = AsyncMock(return_value=[])
    return {
        "team_id": "t", "github_repo": "owner/repo", "github": github,
        "claude": MagicMock(on_event=None), "workspace": str(tmp_path),
    }


@pytest.fixture
async def saver(tmp_path):
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cycle_checkpoints.db")) as s:
        yield s


def _patched(builders: dict, base_state: dict):
    return (
        patch("theswarm.cycle.build_po_graph", builders["po"]),
        patch("theswarm.cycle.build_techlead_graph", builders["tl"]),
        patch("theswarm.cycle.build_dev_graph", builders["dev"]),
        patch("theswarm.cycle.build_qa_graph", builders["qa"]),
        patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock),
        patch("theswarm.cycle._pull_latest", new_callable=AsyncMock),
        patch("theswarm.cycle._build_base_state", return_value=base_state),
        patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock),
        patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock),
        patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock),
    )


async def test_a_cycle_killed_in_qa_resumes_at_qa_and_finishes_once(tmp_path, saver):
    config = CycleConfig(github_repo="owner/repo", team_id="t", workspace_dir=str(tmp_path))
    builders = {
        "po": _Counting({**STUB, "daily_plan": "p", "daily_report": "r"}),
        "tl": _Counting(STUB),
        "dev": _Counting({**STUB, "task": None, "pr": None}),
        "qa": _Counting(QA_OK, fail_first=1),
    }
    phases: list[str] = []

    async def on_progress(role, message):
        if role == PHASE_ROLE:
            phases.append(message)

    patches = _patched(builders, _base_state(tmp_path))
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError, match="mid-flight"):
            await run_daily_cycle(config, on_progress=on_progress, cycle_id="cyc-1", checkpointer=saver)
        first_run = list(phases)
        phases.clear()

        result = await run_daily_cycle(
            config, on_progress=on_progress, cycle_id="cyc-1", checkpointer=saver, resume=True,
        )
    finally:
        for p in patches:
            p.stop()

    assert first_run == ["po_morning", "techlead_breakdown", "dev_loop", "dev_iter", "qa"]
    assert phases == ["qa", "po_evening"]          # resumed where it died
    assert builders["po"].calls == 2                 # morning once, evening once
    assert builders["tl"].calls == 1
    assert builders["dev"].calls == 1
    assert builders["qa"].calls == 2                 # the crash, then the real run
    assert result["demo_report"]["overall_status"] == "green"
    assert result["cost_usd"] == pytest.approx(0.5 * 5)  # po, tl, dev, qa, po — no double count


async def test_resuming_a_thread_that_does_not_exist_is_refused(tmp_path, saver):
    config = CycleConfig(github_repo="", team_id="t")
    with patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        with pytest.raises(CycleNotResumable, match="no checkpoint"):
            await run_daily_cycle(config, cycle_id="never-ran", checkpointer=saver, resume=True)


async def test_a_checkpoint_from_another_schema_is_refused_not_misread(tmp_path, saver, monkeypatch):
    from theswarm import cycle_graph

    config = CycleConfig(github_repo="", team_id="t")
    builders = {
        "po": _Counting({**STUB, "daily_plan": "p"}), "tl": _Counting(STUB),
        "dev": _Counting({**STUB, "task": None, "pr": None}), "qa": _Counting(QA_OK, fail_first=1),
    }
    patches = _patched(builders, {"team_id": "t", "github_repo": "", "github": None, "claude": None, "workspace": None})
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError):
            await run_daily_cycle(config, cycle_id="cyc-2", checkpointer=saver)
        monkeypatch.setattr(cycle_graph, "CYCLE_STATE_SCHEMA_VERSION", CYCLE_STATE_SCHEMA_VERSION + 1)
        with pytest.raises(CycleNotResumable, match="schema"):
            await run_daily_cycle(config, cycle_id="cyc-2", checkpointer=saver, resume=True)
    finally:
        for p in patches:
            p.stop()
    assert builders["qa"].calls == 1  # nothing re-ran on the refused resume


async def test_a_finished_cycle_resumed_returns_its_result_without_running(tmp_path, saver):
    config = CycleConfig(github_repo="", team_id="t")
    builders = {
        "po": _Counting({**STUB, "daily_plan": "p", "daily_report": "done"}), "tl": _Counting(STUB),
        "dev": _Counting({**STUB, "task": None, "pr": None}), "qa": _Counting(QA_OK),
    }
    patches = _patched(builders, {"team_id": "t", "github_repo": "", "github": None, "claude": None, "workspace": None})
    for p in patches:
        p.start()
    try:
        first = await run_daily_cycle(config, cycle_id="cyc-3", checkpointer=saver)
        again = await run_daily_cycle(config, cycle_id="cyc-3", checkpointer=saver, resume=True)
    finally:
        for p in patches:
            p.stop()
    assert again == first
    assert builders["po"].calls == 2  # morning + evening, once each; nothing on the second call


async def test_the_api_runs_a_resume_on_the_interrupted_cycles_thread(monkeypatch):
    from theswarm.api import (
        CycleRequest, CycleStatus, get_cycle_tracker, run_api_cycle, set_cycle_checkpointer,
    )

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_valid_token_for_test")
    saver = object()
    set_cycle_checkpointer(saver)
    seen: dict = {}

    async def fake_run(config, **kwargs):
        seen.update(kwargs)
        return {"date": "d", "cost_usd": 0.0, "prs": [], "reviews": []}

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/repo"))
    try:
        with patch("theswarm.cycle.run_daily_cycle", side_effect=fake_run):
            await run_api_cycle(
                cycle_id=record.id, repo="owner/repo", description="", callback_url="",
                allowed_repos=[], resume_from="qa", resume_cycle_id="old-cycle",
            )
    finally:
        set_cycle_checkpointer(None)

    assert seen["cycle_id"] == "old-cycle"
    assert seen["resume"] is True
    assert seen["checkpointer"] is saver
    assert tracker.get(record.id).status == CycleStatus.COMPLETED


async def test_the_resumer_skips_cycles_without_a_graph_thread(saver):
    from types import SimpleNamespace

    from theswarm.application.services.cycle_resumer import collect_interrupted, plan_resumes

    class Repo:
        async def list_running(self):
            return [SimpleNamespace(id="has-thread", project_id="o/r", triggered_by=""),
                    SimpleNamespace(id="no-thread", project_id="o/r", triggered_by="")]

    class Checkpoints:
        async def last_ok(self, cycle_id):
            return SimpleNamespace(next_phase="qa")

    # give "has-thread" a checkpoint on the graph saver
    from theswarm.cycle_graph import build_cycle_graph, initial_state
    graph = build_cycle_graph(saver)
    await graph.aupdate_state(
        {"configurable": {"thread_id": "has-thread"}}, initial_state("has-thread", "d"),
    )

    items = await collect_interrupted(Repo(), Checkpoints(), graph_checkpointer=saver)
    by_id = {i["cycle_id"]: i["resume_from"] for i in items}
    assert by_id == {"has-thread": "qa", "no-thread": None}
    assert [p.cycle_id for p in plan_resumes(items)] == ["has-thread"]


class _FailOn:
    """A builder whose graphs fail on the given call numbers (1-based)."""

    def __init__(self, state: dict, fail_calls: set[int]):
        self.state = state
        self.calls = 0
        self.fail_calls = fail_calls

    def __call__(self):
        graph = MagicMock()

        async def ainvoke(_state):
            self.calls += 1
            if self.calls in self.fail_calls:
                raise RuntimeError("container replaced mid-flight")
            return dict(self.state)

        graph.ainvoke = AsyncMock(side_effect=ainvoke)
        return graph


async def test_a_resume_mid_dev_loop_hands_back_the_dead_iterations_claims(tmp_path, saver):
    """The dead iteration marked its task in-progress and never handed it
    back; the picker skips claimed tasks, so a resume would find nothing
    ready. The resume hands the claims back before continuing."""
    config = CycleConfig(github_repo="owner/repo", team_id="t", workspace_dir=str(tmp_path))
    builders = {
        "po": _Counting({**STUB, "daily_plan": "p", "daily_report": "r"}),
        # call 1 = breakdown, call 2 = the first review: that is where it dies
        "tl": _FailOn({**STUB, "reviews": [], "merged_prs": [], "held_prs": []}, fail_calls={2}),
        "dev": _Counting({**STUB, "task": {"number": 41}, "pr": {"number": 1, "url": "u"}}),
        "qa": _Counting(QA_OK),
    }
    requeue = AsyncMock(return_value=[41])
    heard: list[tuple[str, str]] = []

    async def on_progress(role, message):
        heard.append((role, message))

    patches = _patched(builders, _base_state(tmp_path)) + (
        patch("theswarm.cycle._requeue_unfinished", requeue),
    )
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError, match="mid-flight"):
            await run_daily_cycle(config, on_progress=on_progress, cycle_id="cyc-4", checkpointer=saver)
        assert builders["dev"].calls == 1
        heard.clear()
        result = await run_daily_cycle(
            config, on_progress=on_progress, cycle_id="cyc-4", checkpointer=saver, resume=True,
        )
    finally:
        for p in patches:
            p.stop()

    assert ("Dev", "Resumed — handing back #41 claimed by the interrupted iteration") in heard
    assert result["prs"]                      # the loop went on after the resume
    assert builders["tl"].calls >= 3          # breakdown, the crash, the review that worked
