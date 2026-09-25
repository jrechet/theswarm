"""A resumed cycle builds the issue it was pinned to, not the backlog.

The first resume on prod (747bb89eced2 → 83b584194589, 2026-09-23) came
back untargeted: the boot resumer started the continuation without the
original issue number, and its Dev opened #279 for #212, an old backlog
issue, beside the two PRs of the pinned feature.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from theswarm.application.services import cycle_resumer
from theswarm.cycle_graph import CycleState, initial_state


def test_the_initial_state_carries_the_target():
    assert initial_state("c1", "2026-09-25", 332)["target_issue"] == 332
    assert initial_state("c1", "2026-09-25")["target_issue"] is None


async def _checkpointed(target_issue):
    """A cycle-shaped graph run once on a saver: what a crash leaves behind."""
    graph = StateGraph(CycleState)
    graph.add_node("prepare", lambda state: {"iteration": 0})
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", END)
    saver = InMemorySaver()
    await graph.compile(checkpointer=saver).ainvoke(
        initial_state("c1", "2026-09-25", target_issue),
        {"configurable": {"thread_id": "c1"}},
    )
    return saver


async def test_the_checkpoint_keeps_the_target():
    saver = await _checkpointed(332)

    thread = await cycle_resumer._graph_thread(saver, "c1")

    assert cycle_resumer._target_issue_of(thread) == 332


async def test_the_interrupted_cycle_names_its_target():
    saver = await _checkpointed(332)
    cycle = SimpleNamespace(id="c1", project_id="o/r", triggered_by="web")
    cycles = SimpleNamespace(list_running=lambda: asyncio.sleep(0, result=[cycle]))
    checkpoints = SimpleNamespace(
        last_ok=lambda cycle_id: asyncio.sleep(0, result=SimpleNamespace(next_phase="dev_loop")),
    )

    (item,) = await cycle_resumer.collect_interrupted(cycles, checkpoints, graph_checkpointer=saver)

    assert item["issue_number"] == 332 and item["resume_from"] == "dev_loop"


async def test_an_untargeted_cycle_stays_untargeted():
    saver = await _checkpointed(None)

    thread = await cycle_resumer._graph_thread(saver, "c1")

    assert cycle_resumer._target_issue_of(thread) is None


def test_the_resume_plan_carries_the_target():
    (plan,) = cycle_resumer.plan_resumes([
        {"cycle_id": "c1", "repo": "o/r", "triggered_by": "web",
         "resume_from": "dev_loop", "issue_number": 332},
    ])

    assert plan.issue_number == 332


async def test_the_continuation_is_started_on_the_same_issue(monkeypatch):
    import theswarm.api as api
    from theswarm.application.services.cycle_resumer import ResumePlan
    from theswarm.presentation.web import server

    launched: dict = {}

    async def fake_run(cycle_id, repo, *args, **kwargs):
        launched.update(kwargs, cycle_id=cycle_id)

    monkeypatch.setattr(api, "run_api_cycle", fake_run)
    repo = SimpleNamespace(mark_resumed=lambda old, new: asyncio.sleep(0))
    plan = ResumePlan(cycle_id="c1", repo="o/r", resume_from="dev_loop", depth=1, issue_number=332)

    await server._launch_resume(SimpleNamespace(state=SimpleNamespace()), plan, [], None, repo, None)
    await asyncio.sleep(0)

    assert launched["issue_number"] == 332
    assert api.get_cycle_tracker().get(launched["cycle_id"]).issue_number == 332
