"""The theater draws the flow from the phases the cycle announced.

The rail guessed: whoever spoke last was active, everyone before them done.
Wrong the moment the TechLead came back to review, or the Dev iterated. The
graph follows the real phases — and an edge carries the hand-off exactly
while its source is done and its target is at work.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.services import progress_bridge
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.routes.v2 import _graph, _stations
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture(autouse=True)
def _isolate():
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    live_before = dict(progress_bridge._LIVE_PROGRESS)
    phases_before = dict(progress_bridge._PHASE_HISTORY)
    yield
    tracker._cycles.clear()
    tracker._cycles.update(before)
    progress_bridge._LIVE_PROGRESS.clear()
    progress_bridge._LIVE_PROGRESS.update(live_before)
    progress_bridge._PHASE_HISTORY.clear()
    progress_bridge._PHASE_HISTORY.update(phases_before)


def _rec(status="running"):
    from theswarm.api import CycleStatus

    return SimpleNamespace(status=CycleStatus(status))


def _phases(*names):
    return [{"phase": n} for n in names]


def _states(graph):
    return {n["key"]: n["state"] for n in graph["nodes"]}


def _flows(graph):
    return {k: e["flow"] for k, e in graph["edge"].items()}


class TestNodesFollowThePhases:
    def test_morning_lights_the_po_only(self):
        g = _graph(_rec(), _phases("po_morning"), [])

        assert _states(g) == {"po": "active", "techlead": "waiting", "dev": "waiting", "qa": "waiting"}
        assert set(_flows(g).values()) == {"idle"}

    def test_breakdown_hands_stories_to_the_techlead(self):
        g = _graph(_rec(), _phases("po_morning", "techlead_breakdown"), [])

        assert _states(g)["po"] == "done"
        assert _states(g)["techlead"] == "active"
        assert _flows(g)["po-techlead"] == "flowing"

    def test_building_hands_tasks_to_the_dev(self):
        g = _graph(_rec(), _phases("po_morning", "techlead_breakdown", "dev_loop", "dev_iter"), [])

        assert _states(g) == {"po": "done", "techlead": "done", "dev": "active", "qa": "waiting"}
        assert _flows(g)["techlead-dev"] == "flowing"
        assert _flows(g)["dev-techlead"] == "idle"

    def test_review_brings_the_techlead_back(self):
        """The old rail could not say this: the TechLead is active again
        *after* the Dev, and the Dev is done."""
        g = _graph(_rec(), _phases(
            "po_morning", "techlead_breakdown", "dev_loop", "dev_iter", "techlead_review",
        ), [])

        assert _states(g)["techlead"] == "active"
        assert _states(g)["dev"] == "done"
        assert _flows(g)["dev-techlead"] == "flowing"
        assert _flows(g)["techlead-dev"] == "idle"

    def test_a_second_iteration_puts_the_dev_back_to_work(self):
        g = _graph(_rec(), _phases(
            "po_morning", "techlead_breakdown", "dev_loop",
            "dev_iter", "techlead_review", "dev_iter",
        ), [])

        assert _states(g)["dev"] == "active"
        assert _states(g)["techlead"] == "done"
        assert _flows(g)["techlead-dev"] == "flowing"

    def test_qa_receives_the_merged_work(self):
        g = _graph(_rec(), _phases(
            "po_morning", "techlead_breakdown", "dev_loop", "dev_iter", "techlead_review", "qa",
        ), [])

        assert _states(g)["qa"] == "active"
        assert _flows(g)["techlead-qa"] == "flowing"
        assert _flows(g)["qa-po"] == "idle"

    def test_the_evening_report_comes_back_to_the_po(self):
        g = _graph(_rec(), _phases(
            "po_morning", "techlead_breakdown", "dev_loop", "dev_iter",
            "techlead_review", "qa", "po_evening",
        ), [])

        assert _states(g)["po"] == "active"
        assert _states(g)["qa"] == "done"
        assert _flows(g)["qa-po"] == "flowing"
        assert _flows(g)["po-techlead"] == "idle"

    def test_the_active_node_names_its_phase(self):
        g = _graph(_rec(), _phases("po_morning", "techlead_breakdown", "dev_loop", "dev_iter", "techlead_review"), [])
        by_key = {n["key"]: n for n in g["nodes"]}

        assert by_key["techlead"]["phase"] == "reviewing"
        assert by_key["dev"]["phase"] == ""

    def test_unknown_phases_are_ignored(self):
        g = _graph(_rec(), _phases("po_morning", "something_new"), [])

        assert _states(g)["po"] == "active"


class TestTerminalStates:
    def test_failure_lands_on_the_owner_of_the_current_phase(self):
        g = _graph(_rec("failed"), _phases("po_morning", "techlead_breakdown", "dev_loop", "dev_iter"), [])

        assert _states(g) == {"po": "done", "techlead": "done", "dev": "failed", "qa": "waiting"}

    def test_cancellation_reads_like_a_failure_where_it_stopped(self):
        g = _graph(_rec("cancelled"), _phases("po_morning", "techlead_breakdown"), [])

        assert _states(g)["techlead"] == "failed"
        assert _states(g)["po"] == "done"

    def test_completed_marks_everything_that_ran_done(self):
        g = _graph(_rec("completed"), _phases(
            "po_morning", "techlead_breakdown", "dev_loop", "dev_iter",
            "techlead_review", "qa", "po_evening",
        ), [])

        assert set(_states(g).values()) == {"done"}
        assert set(_flows(g).values()) == {"done"}

    def test_completed_does_not_pretend_a_node_that_never_ran_did(self):
        g = _graph(_rec("completed"), _phases("po_morning", "qa", "po_evening"), [])

        assert _states(g)["dev"] == "waiting"
        assert _states(g)["techlead"] == "waiting"


class TestWithoutAnnouncedPhases:
    def test_falls_back_to_the_freshest_role_rail(self):
        progress = [
            {"role": "dev", "message": "Implementing the model"},
            {"role": "techlead", "message": "Split into 3 tasks"},
        ]

        g = _graph(_rec(), [], progress)

        expected = {s["key"]: s["state"] for s in _stations(_rec(), progress)}
        assert _states(g) == expected
        assert _flows(g)["techlead-dev"] == "flowing"

    def test_messages_still_ride_along(self):
        progress = [{"role": "dev", "message": "Writing tests for the model"}]

        g = _graph(_rec(), _phases("po_morning", "techlead_breakdown", "dev_loop", "dev_iter"), progress)

        assert {n["key"]: n["message"] for n in g["nodes"]}["dev"] == "Writing tests for the model"


class TestEdgeCounts:
    def test_tasks_and_reviews_come_from_the_pinned_issue(self):
        pinned = SimpleNamespace(children=[{}, {}, {}], done=2)

        g = _graph(_rec(), _phases("po_morning"), [], pinned)

        assert g["edge"]["techlead-dev"]["count"] == 3
        assert g["edge"]["dev-techlead"]["count"] == 2

    def test_no_pinned_issue_means_no_counts(self):
        g = _graph(_rec(), _phases("po_morning"), [], None)

        assert g["edge"]["techlead-dev"]["count"] is None


# ── The page ───────────────────────────────────────────────────────────


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await conn.close()


def _record():
    from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=21))
    tracker.update_status(record.id, CycleStatus.RUNNING)
    return tracker.get(record.id)


async def test_the_stage_draws_the_hand_off_in_flight(web):
    record = _record()
    for phase in ("po_morning", "techlead_breakdown", "dev_loop", "dev_iter"):
        progress_bridge.record_phase(record.id, phase)
    progress_bridge.record_live_progress(record.id, "dev", "Implementing #22")

    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(return_value=None)
        r = await web.get(f"/c/{record.id}/stage")

    assert r.status_code == 200
    assert 'data-testid="flow"' in r.text
    assert 'data-edge="techlead-dev" data-flow="flowing"' in r.text
    assert 'data-edge="po-techlead" data-flow="done"' in r.text
    assert 'data-role="dev" data-state="active"' in r.text
    assert 'data-testid="node-phase">building<' in r.text


async def test_the_arcs_follow_the_review(web):
    record = _record()
    for phase in ("po_morning", "techlead_breakdown", "dev_loop", "dev_iter", "techlead_review"):
        progress_bridge.record_phase(record.id, phase)

    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(return_value=None)
        r = await web.get(f"/c/{record.id}/stage")

    assert 'data-edge="dev-techlead" data-flow="flowing"' in r.text
    assert 'data-edge="techlead-qa" data-flow="idle"' in r.text
    assert 'data-role="techlead" data-state="active"' in r.text


async def test_a_cycle_without_phases_still_renders(web):
    record = _record()

    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(return_value=None)
        r = await web.get(f"/c/{record.id}/stage")

    assert r.status_code == 200
    assert 'data-testid="agent-rail"' in r.text
    assert 'data-role="po" data-state="active"' in r.text
