"""The swarm's MCP server (phase B, B5 — read and pilot).

A client such as Claude Code talks to `/mcp`: it lists projects, teams and
cycles, starts a feature, talks to a running cycle, pauses it. Behind the
wall, the owner's; an agent's change to a team is not a tool here.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker
from theswarm.application.events.bus import EventBus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.mcp import protocol
from theswarm.presentation.web.mcp.tools import TOOLS
from theswarm.presentation.web.sse import SSEHub

APP = "jrechet/concert-tour-app"


@pytest.fixture
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "m.db"))
    projects = SQLiteProjectRepository(conn)
    await projects.save(Project(id="concert-tour-app", repo=RepoUrl(APP)))
    app = create_web_app(projects, SQLiteCycleRepository(conn), EventBus(), SSEHub(), base_path="/swarm", db=conn,
                         cycle_event_store=SQLiteCycleEventStore(conn))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    await conn.close()


async def _rpc(client, method, params=None, request_id=1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return await client.post("/mcp", json=body)


async def _call(client, name, arguments=None):
    answer = (await _rpc(client, "tools/call", {"name": name, "arguments": arguments or {}})).json()["result"]
    text = answer["content"][0]["text"]
    return answer["isError"], (json.loads(text) if not answer["isError"] else text)


# ── The protocol ───────────────────────────────────────────────────────


async def test_a_client_initializes_and_reads_the_tools(web):
    client, _ = web
    hello = (await _rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                              "clientInfo": {"name": "claude-code", "version": "2"}})).json()["result"]
    assert hello["protocolVersion"] == "2025-03-26" and hello["serverInfo"]["name"] == "theswarm"
    assert hello["capabilities"] == {"tools": {"listChanged": False}}

    note = await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert note.status_code == 202 and note.content == b""
    assert (await _rpc(client, "ping")).json()["result"] == {}

    tools = (await _rpc(client, "tools/list")).json()["result"]["tools"]
    assert [t["name"] for t in tools] == list(TOOLS)
    start = next(t for t in tools if t["name"] == "start_feature")
    assert start["inputSchema"]["required"] == ["project"] and start["annotations"]["readOnlyHint"] is False
    assert next(t for t in tools if t["name"] == "get_cycle")["annotations"]["readOnlyHint"] is True


async def test_what_is_not_the_protocol_is_refused_in_its_words(web):
    client, _ = web
    assert (await _rpc(client, "resources/list")).json()["error"]["code"] == protocol.METHOD_NOT_FOUND
    assert (await client.post("/mcp", content=b"{not json")).status_code == 400
    assert (await client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])).status_code == 400
    assert (await _rpc(client, "tools/call", {"name": "drop_database"})).json()["error"]["code"] == protocol.INVALID_PARAMS
    assert (await client.get("/mcp")).status_code == 405
    wrong, said = await _call(client, "get_cycle", {})
    assert wrong and said == "get_cycle needs cycle_id"
    wrong, said = await _call(client, "get_cycle", {"cycle_id": "abc", "verbose": True})
    assert wrong and "not verbose" in said


def test_a_member_cannot_reach_it():
    from theswarm.presentation.web.auth import MEMBER_ALLOWED

    assert not MEMBER_ALLOWED.match("/mcp")


# ── Reading ────────────────────────────────────────────────────────────


async def test_projects_teams_and_a_team_file(web):
    client, app = web
    _, projects = await _call(client, "list_projects")
    assert projects["projects"] == [{"project": APP, "cycles_at_once": 2, "live_cycles": 0}]

    await app.state.personas.save(APP, "dev", name="Aarav", instructions="Type every function.")
    _, team = await _call(client, "get_team", {"project": APP})
    dev = next(r for r in team["roles"] if r["role"] == "dev")
    assert dev["name"] == "Aarav" and dev["instructions"] == "Type every function." and "name: Aarav" in team["team_yaml"]
    wrong, said = await _call(client, "get_team", {"project": "o/unknown"})
    assert wrong and "not a registered project" in said

    _, verdict = await _call(client, "validate_team_yaml", {"yaml": "format: 1\npersonas:\n  dev: {model: gpt}", "project": APP})
    assert verdict["valid"] is False and "not one of" in verdict["problem"]
    _, verdict = await _call(client, "validate_team_yaml", {"yaml": team["team_yaml"], "project": APP})
    assert verdict == {"valid": True, "roles_written": ["dev"],
                       "note": "Valid. Nothing was changed: the owner imports a team in Settings → Agents."}
    assert app.state.personas.stored(APP, "dev").name == "Aarav"  # validating changes nothing


async def test_a_cycle_is_read_with_what_its_agents_said(web):
    from theswarm.application.services import progress_bridge
    from theswarm.domain.cycles.events import AgentActivity
    from theswarm.domain.cycles.value_objects import CycleId

    client, app = web
    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo=APP, issue_number=905))
    tracker.update_status(record.id, CycleStatus.RUNNING)
    tracker.add_spend(record.id, 1.237)
    progress_bridge.record_phase(record.id, "dev_iter")
    await app.state.event_bus.publish(AgentActivity(cycle_id=CycleId(record.id), project_id=APP, agent="Dev",
                                                    action="progress", detail="Running tests"))
    try:
        _, cycle = await _call(client, "get_cycle", {"cycle_id": record.id})
        assert cycle["status"] == "running" and cycle["phase"] == "dev_iter" and cycle["spent_usd"] == 1.24
        assert cycle["last_said"][-1]["said"] == "Running tests" and cycle["theater"].endswith(f"/cycles/{record.id}")
        _, listed = await _call(client, "list_cycles", {"project": APP})
        assert [c["cycle_id"] for c in listed["cycles"]] == [record.id]
        wrong, said = await _call(client, "get_cycle", {"cycle_id": "nope"})
        assert wrong and "No cycle" in said
    finally:
        tracker._cycles.pop(record.id, None)
        progress_bridge._PHASE_HISTORY.pop(record.id, None)


# ── Piloting ───────────────────────────────────────────────────────────


async def test_a_feature_is_started_as_the_composer_does(web):
    client, _ = web
    started = AsyncMock(return_value=type("R", (), {"id": "abc123abc123", "status": CycleStatus.QUEUED})())
    with patch("theswarm.tools.github.GitHubClient") as klass, \
            patch("theswarm.presentation.web.routes.common.start_targeted_cycle", new=started):
        klass.return_value.create_issue = AsyncMock(return_value={"number": 950})
        _, answer = await _call(client, "start_feature", {
            "project": APP, "title": "Search the venues", "description": "GET /api/v1/venues/search?q=…"})
        klass.return_value.create_issue.assert_awaited_once_with(
            title="Search the venues", body="GET /api/v1/venues/search?q=…", labels=["status:backlog"])
    assert answer["cycle_id"] == "abc123abc123" and answer["issue_number"] == 950
    assert started.await_args.args[1:4] == ("jrechet", "concert-tour-app", 950)

    with patch("theswarm.presentation.web.routes.common.start_targeted_cycle", new=started):
        _, again = await _call(client, "start_feature", {"project": APP, "issue_number": 905})  # an existing issue
    assert again["issue_number"] == 905

    for bad in ({"project": APP}, {"project": APP, "title": "x", "issue_number": 1}, {"project": "o/unknown", "title": "x"}):
        wrong, _ = await _call(client, "start_feature", bad)
        assert wrong


async def test_a_running_cycle_is_told_and_paused(web):
    client, app = web
    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo=APP, issue_number=905))
    tracker.update_status(record.id, CycleStatus.RUNNING)

    async def forever():
        await asyncio.sleep(60)

    task = asyncio.create_task(forever())
    tracker.set_task(record.id, task)
    try:
        _, sent = await _call(client, "say_to_cycle", {"cycle_id": record.id, "message": "Use the existing schema"})
        assert sent["sent"] and await app.state.cycle_inbox.waiting(record.id) == 1
        _, cut = await _call(client, "say_to_cycle", {"cycle_id": record.id, "message": "Stop renaming", "stop": True})
        assert "cut" in cut["note"]
        assert await app.state.cycle_inbox.take(record.id, to="Dev", urgent_only=True) == ["Stop renaming"]

        _, paused = await _call(client, "pause_cycle", {"cycle_id": record.id})
        assert paused["pausing"] and tracker.pause_requested(record.id)

        tracker.update_status(record.id, CycleStatus.COMPLETED)
        for tool, arguments in (("say_to_cycle", {"cycle_id": record.id, "message": "late"}),
                                ("pause_cycle", {"cycle_id": record.id})):
            wrong, said = await _call(client, tool, arguments)
            assert wrong and "is not running" in said
    finally:
        task.cancel()
        tracker._cycles.pop(record.id, None)
        tracker._pause_requested.discard(record.id)


async def test_a_tool_that_breaks_says_so_without_its_insides(web):
    client, app = web
    app.state.project_repo = type("Broken", (), {"list_all": AsyncMock(side_effect=RuntimeError("database is locked /srv/x"))})()
    wrong, said = await _call(client, "list_projects")
    assert wrong and said == "list_projects failed: RuntimeError"
