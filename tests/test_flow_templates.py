"""Flow templates (phase B, B3): a cycle follows the feature flow, the fix
flow or the review flow — a label on its issue says which."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm import cycle_graph
from theswarm.domain.cycles.value_objects import CYCLE_NODE_ROLES
from theswarm.domain.teams.templates import (
    FEATURE, FIX, REVIEW, TEMPLATES, flow_labels, flow_of_labels, template,
)


# ── The templates ──────────────────────────────────────────────────────


def test_three_flows_each_a_path_through_the_one_graph():
    assert [t.key for t in TEMPLATES] == [FEATURE, FIX, REVIEW]
    nodes = set(cycle_graph.build_cycle_graph().get_graph().nodes) - {"__start__", "__end__"}
    for flow in TEMPLATES:
        assert set(flow.path) <= nodes, flow.key
        assert flow.path[0] == "prepare" and flow.path[-2:] == ("finish", "cycle_log")
    assert "techlead_breakdown" not in template(FIX).path and "qa" in template(FIX).path
    assert "dev_iter" not in template(REVIEW).path and "qa" not in template(REVIEW).path
    assert "techlead_review" in template(REVIEW).path  # no flow drops the review


def test_the_flow_is_a_label_on_the_issue():
    assert flow_labels() == ("flow:fix", "flow:review") and template(FEATURE).label == ""
    assert flow_of_labels([{"name": "status:backlog"}, {"name": "flow:fix"}]) == FIX
    assert flow_of_labels(["flow:review"]) == REVIEW
    assert flow_of_labels([{"name": "status:ready"}]) == flow_of_labels(None) == FEATURE
    assert template("nonsense").key == FEATURE


def test_every_node_a_flow_announces_has_an_owner():
    assert CYCLE_NODE_ROLES["fix_intake"] == "techlead"


# ── The graph follows it ───────────────────────────────────────────────


def test_the_routing():
    assert cycle_graph._after_prepare({}) == "po_morning"  # a checkpoint from before B3
    assert cycle_graph._after_prepare({"template": FEATURE}) == "po_morning"
    assert cycle_graph._after_prepare({"template": FIX}) == "fix_intake"
    assert cycle_graph._after_prepare({"template": REVIEW}) == "techlead_review"
    assert cycle_graph._after_review({"template": REVIEW}) == "dev_loop_end"  # nothing to build after it
    assert cycle_graph._after_dev_loop_end({"template": REVIEW}) == "merge_held"
    assert cycle_graph._after_dev_loop_end({"template": FIX}) == cycle_graph._after_dev_loop_end({}) == "qa"
    assert cycle_graph._after_qa({"template": FIX}) == "merge_held"
    assert cycle_graph._after_qa({}) == cycle_graph._after_qa({"template": FEATURE}) == "po_evening"


def _runtime(github, real=True):
    said: list[tuple[str, str]] = []

    async def progress(role, text):
        said.append((role, text))

    rt = SimpleNamespace(config=SimpleNamespace(is_real_mode=real), base_state={"github": github}, progress=progress,
                         watchdog=None, enter=AsyncMock(), phase_checkpoint=AsyncMock())
    return SimpleNamespace(context=rt), said


async def test_prepare_reads_the_flow_off_the_pinned_issue():
    github = SimpleNamespace(ensure_branch_protection=AsyncMock(),
                             get_issue=AsyncMock(return_value={"number": 7, "labels": [{"name": "flow:fix"}]}))
    runtime, said = _runtime(github)
    assert await cycle_graph.prepare({"target_issue": 7}, runtime) == {"template": FIX}
    assert any(text.startswith("Flow: Fix") for _, text in said)

    github.get_issue = AsyncMock(return_value={"number": 7, "labels": []})
    assert (await cycle_graph.prepare({"target_issue": 7}, runtime))["template"] == FEATURE
    github.get_issue = AsyncMock(side_effect=RuntimeError("GitHub 502"))
    assert (await cycle_graph.prepare({"target_issue": 7}, runtime))["template"] == FEATURE  # unreadable: the whole flow
    assert (await cycle_graph.prepare({}, runtime))["template"] == FEATURE  # an unpinned cycle


async def test_a_fix_s_issue_becomes_the_dev_s_task():
    github = SimpleNamespace(add_labels=AsyncMock(), remove_label=AsyncMock())
    runtime, said = _runtime(github)
    await cycle_graph.fix_intake({"target_issue": 7, "template": FIX}, runtime)
    github.add_labels.assert_awaited_once_with(7, ["role:dev", "status:ready"])
    assert said == [("TechLead", "Fix: #7 is one task — no breakdown, straight to the Dev")]

    from theswarm.agents.dev import _pick_targeted

    picked = await _pick_targeted(
        SimpleNamespace(get_issue=AsyncMock(return_value={
            "number": 7, "state": "open", "labels": [{"name": "role:dev"}, {"name": "status:ready"}, {"name": "flow:fix"}]})),
        7, [])
    assert picked["number"] == 7  # the Dev takes the pinned issue itself


# ── Play writes it ─────────────────────────────────────────────────────


async def test_play_writes_the_flow_on_the_issue():
    from theswarm.presentation.web.routes import common

    with patch("theswarm.tools.github.GitHubClient") as klass:
        client = klass.return_value
        client.add_labels, client.remove_label = AsyncMock(), AsyncMock()
        assert await common.set_flow("o/r", 7, "fix") == FIX
        client.add_labels.assert_awaited_once_with(7, ["flow:fix"])
        client.remove_label.assert_awaited_once_with(7, "flow:review")

        client.add_labels.reset_mock(), client.remove_label.reset_mock()
        assert await common.set_flow("o/r", 7, "feature") == FEATURE  # no label: both taken off
        client.add_labels.assert_not_awaited()
        assert [c.args[1] for c in client.remove_label.await_args_list] == ["flow:fix", "flow:review"]

        client.remove_label = AsyncMock(side_effect=RuntimeError("GitHub 502"))
        assert await common.set_flow("o/r", 7, "review") == REVIEW  # never raises


async def test_the_mcp_starts_a_feature_on_a_flow(tmp_path):
    from tests.presentation.test_mcp_server import APP, _call
    from httpx import ASGITransport, AsyncClient

    from theswarm.api import CycleStatus
    from theswarm.application.events.bus import EventBus
    from theswarm.domain.projects.entities import Project
    from theswarm.domain.projects.value_objects import RepoUrl
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository, init_db
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    conn = await init_db(str(tmp_path / "f.db"))
    try:
        projects = SQLiteProjectRepository(conn)
        await projects.save(Project(id="concert-tour-app", repo=RepoUrl(APP)))
        app = create_web_app(projects, SQLiteCycleRepository(conn), EventBus(), SSEHub(), base_path="/swarm", db=conn)
        started = AsyncMock(return_value=type("R", (), {"id": "abc123abc123", "status": CycleStatus.QUEUED})())
        flows = AsyncMock(return_value="fix")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("theswarm.presentation.web.routes.common.start_targeted_cycle", new=started), \
                    patch("theswarm.presentation.web.routes.common.set_flow", new=flows):
                wrong, _ = await _call(client, "start_feature", {"project": APP, "issue_number": 905, "flow": "fix"})
                assert not wrong
                flows.assert_awaited_once_with(APP, 905, "fix")
                wrong, said = await _call(client, "start_feature", {"project": APP, "issue_number": 905, "flow": "canvas"})
                assert wrong and "flow is one of" in said
    finally:
        await conn.close()
