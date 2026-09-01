"""The theater: four stations, a pinned issue, a live feed."""

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
from theswarm.presentation.web.routes.v2 import _stations
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture(autouse=True)
def _isolate_tracker_and_progress():
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    progress_before = dict(progress_bridge._LIVE_PROGRESS)
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)
    progress_bridge._LIVE_PROGRESS.clear()
    progress_bridge._LIVE_PROGRESS.update(progress_before)


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await conn.close()


def _record(status="running", issue=21):
    from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker

    tracker = get_cycle_tracker()
    record = tracker.create(
        CycleRequest(repo="jrechet/concert-tour-app", issue_number=issue),
    )
    tracker.update_status(record.id, CycleStatus(status))
    return tracker.get(record.id)


def _rec(status):
    from theswarm.api import CycleStatus

    return SimpleNamespace(status=CycleStatus(status))


# ── Station states from live progress ──────────────────────────────────


def test_freshest_role_is_the_active_station():
    progress = [  # most recent first — the bridge's contract
        {"role": "dev", "message": "Implementing the waiting list model"},
        {"role": "techlead", "message": "Split into 3 tasks"},
        {"role": "po", "message": "Shaped #21"},
    ]
    states = {s["key"]: s["state"] for s in _stations(_rec("running"), progress)}
    assert states == {
        "po": "done", "techlead": "done", "dev": "active", "qa": "waiting",
    }


def test_running_with_no_progress_yet_lights_the_po():
    states = {s["key"]: s["state"] for s in _stations(_rec("running"), [])}
    assert states["po"] == "active"
    assert states["qa"] == "waiting"


def test_completed_cycle_marks_every_station_done():
    states = {s["key"]: s["state"] for s in _stations(_rec("completed"), [])}
    assert set(states.values()) == {"done"}


def test_failure_lands_on_the_active_station():
    progress = [{"role": "qa", "message": "Running the e2e suite"}]
    states = {s["key"]: s["state"] for s in _stations(_rec("failed"), progress)}
    assert states == {
        "po": "done", "techlead": "done", "dev": "done", "qa": "failed",
    }


def test_station_carries_its_last_message():
    progress = [{"role": "dev", "message": "Writing tests for the model"}]
    stations = {s["key"]: s for s in _stations(_rec("running"), progress)}
    assert stations["dev"]["message"] == "Writing tests for the model"


# ── The page ───────────────────────────────────────────────────────────


async def test_theater_renders_rail_issue_and_feed(web):
    client, _ = web
    record = _record()
    progress_bridge.record_live_progress(record.id, "dev", "Implementing #22")

    pinned_issue = {"number": 21, "title": "Fans can join a waiting list"}
    children = [
        {"number": 22, "title": "Waiting list model", "labels": ["status:in-progress"],
         "body": "Parent: #21"},
        {"number": 23, "title": "Notify on freed seat", "labels": ["status:review"],
         "body": "Parent: #21"},
    ]
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(return_value=pinned_issue)
        klass.return_value.get_issues = AsyncMock(return_value=children)
        r = await client.get(f"/c/{record.id}")

    assert r.status_code == 200
    assert 'data-testid="agent-rail"' in r.text
    assert "Fans can join a waiting list" in r.text
    assert "1/2 done" in r.text
    assert 'data-state="active"' in r.text
    assert "Implementing #22" in r.text


async def test_stage_fragment_carries_the_status_for_the_poll_loop(web):
    client, _ = web
    record = _record(status="running")
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(return_value=None)
        r = await client.get(f"/c/{record.id}/stage")

    assert r.status_code == 200
    assert 'data-status="running"' in r.text


async def test_unknown_cycle_is_a_404(web):
    client, _ = web
    r = await client.get("/c/does-not-exist")
    assert r.status_code == 404


async def test_historical_cycle_redirects_to_the_archive_view(web):
    client, app = web
    from datetime import datetime, timezone

    from theswarm.domain.cycles.entities import Cycle
    from theswarm.domain.cycles.value_objects import CycleId, CycleStatus

    cycle = Cycle(
        id=CycleId("cafe1234cafe"), project_id="p", status=CycleStatus.COMPLETED,
        triggered_by="test", started_at=datetime.now(timezone.utc),
    )
    await app.state.cycle_repo.save(cycle)

    r = await client.get("/c/cafe1234cafe")

    assert r.status_code == 303
    assert r.headers["location"] == "/swarm/cycles/cafe1234cafe"


async def test_play_now_lands_on_the_theater(web):
    client, _ = web
    with patch("theswarm.api.run_api_cycle", new=AsyncMock()):
        r = await client.post("/r/jrechet/concert-tour-app/issues/7/play")

    assert r.status_code == 303
    assert "/swarm/c/" in r.headers["location"]
    assert "/cycles/" not in r.headers["location"]
