"""Pausing a cycle and resuming it (A3.2).

A pause is taken between two phases: the phase in flight finishes and is
checkpointed, the next one raises `PauseRequested` at its door before any
effect, the cycle's place is given back, and Resume goes on from that phase
on the same graph thread — the restart's path.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm import cycle_graph
from theswarm.api import CycleRequest, CycleStatus, CycleTracker
from theswarm.cycle_budgets import PauseRequested


def _runtime(asked):
    return SimpleNamespace(context=SimpleNamespace(should_pause=asked))


async def test_a_pause_is_taken_at_the_door_of_the_next_node():
    ran: list[str] = []

    async def node(state, runtime):
        ran.append("qa")
        return {"ok": True}

    door = cycle_graph._pausable("qa", node)
    assert await door({}, _runtime(lambda: False)) == {"ok": True}
    assert await door({}, _runtime(None)) == {"ok": True}  # the CLI: nobody to ask
    with pytest.raises(PauseRequested) as caught:
        await door({}, _runtime(lambda: True))
    assert caught.value.before == "qa" and ran == ["qa", "qa"]  # the paused node did nothing


async def test_the_graph_stops_between_two_nodes_and_resumes_at_the_one_it_left():
    """On the real graph machinery: the node in flight is checkpointed, the
    next one is not run, and a resume on the thread runs it."""
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, StateGraph

    asked = {"pause": False}
    rt = SimpleNamespace(should_pause=lambda: asked["pause"])

    async def first(state, runtime):
        asked["pause"] = True  # the owner clicks Pause while this phase runs
        return {"reviewed_prs": [*state.get("reviewed_prs", []), "first"]}

    async def second(state, runtime):
        return {"reviewed_prs": [*state.get("reviewed_prs", []), "second"]}

    graph = StateGraph(cycle_graph.CycleState, context_schema=SimpleNamespace)
    graph.add_node("first", cycle_graph._pausable("first", first))
    graph.add_node("second", cycle_graph._pausable("second", second))
    graph.set_entry_point("first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)
    app = graph.compile(checkpointer=MemorySaver())
    thread = {"configurable": {"thread_id": "t1"}}

    with pytest.raises(PauseRequested):
        await app.ainvoke({"reviewed_prs": []}, thread, context=rt, durability="sync")
    assert (await app.aget_state(thread)).values["reviewed_prs"] == ["first"]

    asked["pause"] = False  # the continuation is another cycle: nobody paused it
    final = await app.ainvoke(None, thread, context=rt, durability="sync")
    assert final["reviewed_prs"] == ["first", "second"]


async def test_only_a_running_cycle_can_be_paused():
    tracker = CycleTracker()
    record = tracker.create(CycleRequest(repo="o/r", issue_number=1))
    assert tracker.pause(record.id) is False  # queued, no task

    async def forever():
        await asyncio.sleep(60)

    task = asyncio.create_task(forever())
    tracker.set_task(record.id, task)
    assert tracker.pause(record.id) is False  # still queued
    tracker.update_status(record.id, CycleStatus.RUNNING)
    assert tracker.pause(record.id) is True and tracker.pause_requested(record.id)
    assert not tracker.cancel_requested(record.id)
    task.cancel()
    assert tracker.pause("nope") is False


async def test_the_runner_ends_it_paused_not_failed(monkeypatch):
    from theswarm import api

    published: list = []

    class _Bus:
        async def publish(self, event):
            published.append(event)

    tracker = api.get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=905))

    async def paused_cycle(*args, **kwargs):
        assert kwargs["should_pause"]() is False
        raise PauseRequested("qa")

    monkeypatch.setattr(api, "run_daily_cycle", paused_cycle, raising=False)
    monkeypatch.setattr("theswarm.cycle.run_daily_cycle", paused_cycle)
    monkeypatch.setattr("theswarm.tools.github.verify_access", AsyncMock())
    try:
        await api._run_api_cycle(record.id, "jrechet/concert-tour-app", "", "", ["jrechet/concert-tour-app"],
                                 event_bus=_Bus(), issue_number=905)
        assert tracker.get(record.id).status == CycleStatus.PAUSED and tracker.get(record.id).error is None
        kinds = [type(e).__name__ for e in published]
        assert "CyclePaused" in kinds and "CycleFailed" not in kinds
        said = next(e for e in published if type(e).__name__ == "AgentActivity" and e.action == "paused")
        assert said.detail.startswith("Paused before qa")
    finally:
        tracker._cycles.pop(record.id, None)


async def test_the_row_says_paused_and_the_boot_leaves_it(tmp_path):
    from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
    from theswarm.domain.cycles.events import CyclePaused, CycleStarted
    from theswarm.domain.cycles.value_objects import CycleId
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, init_db

    conn = await init_db(str(tmp_path / "p.db"))
    try:
        repo = SQLiteCycleRepository(conn)
        handler = CyclePersistenceHandler(repo)
        cid = CycleId("abc123def456")
        await handler.handle(CycleStarted(cycle_id=cid, project_id="o/r", triggered_by="web"))
        await handler.handle(CyclePaused(cycle_id=cid, project_id="o/r", before="qa", total_cost_usd=1.25))

        row = await repo.get(cid)
        assert row.status.value == "paused" and row.total_cost_usd == 1.25
        assert [str(c.id) for c in await repo.list_running()] == []  # the resumer reads the running ones
    finally:
        await conn.close()


async def _theater(tmp_path, status):
    from theswarm.api import get_cycle_tracker
    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository,
        SQLiteProjectRepository,
        init_db,
    )
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=905))
    tracker.update_status(record.id, status)
    conn = await init_db(str(tmp_path / "t.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(),
                         base_path="/swarm", db=conn, cycle_event_store=SQLiteCycleEventStore(conn))
    return tracker, record, conn, app


async def test_the_theater_pauses_a_running_cycle_and_says_so(tmp_path):
    from httpx import ASGITransport, AsyncClient

    tracker, record, conn, app = await _theater(tmp_path, CycleStatus.RUNNING)

    async def forever():
        await asyncio.sleep(60)

    task = asyncio.create_task(forever())
    tracker.set_task(record.id, task)
    try:
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issue = AsyncMock(return_value={"number": 905, "title": "Change a venue"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                assert 'data-testid="pause"' in (await client.get(f"/cycles/{record.id}")).text
                answer = await client.post(f"/cycles/{record.id}/pause")
                assert answer.status_code == 303 and tracker.pause_requested(record.id)
                page = (await client.get(f"/cycles/{record.id}")).text
                assert 'data-testid="pausing"' in page and 'data-testid="pause"' not in page

                tracker.update_status(record.id, CycleStatus.PAUSED)
                page = (await client.get(f"/cycles/{record.id}")).text
                assert "Paused" in page and 'data-testid="pausing"' not in page
    finally:
        task.cancel()
        tracker._cycles.pop(record.id, None)
        tracker._pause_requested.discard(record.id)
        await conn.close()
