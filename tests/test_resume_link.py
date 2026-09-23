"""A resumed cycle can be followed: the row, the API, the theater, the harness.

A restart reaps the interrupted row to 'failed' and the boot resumer goes on
under a new tracker id (V2 runtime, M4). Before this link the harness scored
the old id as a failure, the theater showed it dead, and every resumed cycle
was recorded as triggered from the web, so the one-resume cap never held.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolate_tracker():
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)


@pytest.fixture()
async def conn(tmp_path):
    db = await init_db(str(tmp_path / "link.db"))
    yield db
    await db.close()


@pytest.fixture()
async def web(conn):
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app


def _interrupted(cycle_id: str = "old123old123") -> Cycle:
    now = datetime.now(timezone.utc)
    return Cycle(
        id=CycleId(cycle_id), project_id="jrechet/concert-tour-app",
        status=CycleStatus.FAILED, triggered_by="web",
        started_at=now, completed_at=now,
    )


def _tracked(repo: str = "jrechet/concert-tour-app"):
    from theswarm.api import CycleRequest, CycleStatus as TrackerStatus, get_cycle_tracker

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo=repo))
    tracker.update_status(record.id, TrackerStatus.RUNNING)
    return tracker.get(record.id)


# ── The row ────────────────────────────────────────────────────────────


async def test_the_link_is_stored_and_read_back(conn):
    repo = SQLiteCycleRepository(conn)
    await repo.save(_interrupted())

    await repo.mark_resumed("old123old123", "new456new456")

    assert (await repo.get(CycleId("old123old123"))).resumed_as == "new456new456"


async def test_a_later_save_keeps_the_link(conn):
    from dataclasses import replace

    repo = SQLiteCycleRepository(conn)
    await repo.save(_interrupted())
    await repo.mark_resumed("old123old123", "new456new456")

    cycle = await repo.get(CycleId("old123old123"))
    await repo.save(replace(cycle, total_cost_usd=1.5))

    assert (await repo.get(CycleId("old123old123"))).resumed_as == "new456new456"


def test_every_handler_rebuild_carries_the_link():
    source = (ROOT / "src/theswarm/application/events/persistence_handlers.py").read_text()
    assert source.count("trace_id=cycle.trace_id") == source.count("resumed_as=cycle.resumed_as")


async def test_an_existing_database_gains_the_column(tmp_path):
    import aiosqlite

    from theswarm.infrastructure.persistence.sqlite_repos import _ensure_cycles_columns

    db = await aiosqlite.connect(str(tmp_path / "old.db"))
    await db.execute("CREATE TABLE cycles (id TEXT PRIMARY KEY)")
    await _ensure_cycles_columns(db)
    await _ensure_cycles_columns(db)  # idempotent
    cursor = await db.execute("PRAGMA table_info(cycles)")
    columns = {row[1] for row in await cursor.fetchall()}
    await db.close()

    assert {"trace_id", "resumed_as"} <= columns


# ── The API ────────────────────────────────────────────────────────────


async def test_the_api_names_the_continuation(web):
    client, app = web
    await app.state.cycle_repo.save(_interrupted())
    await app.state.cycle_repo.mark_resumed("old123old123", "new456new456")

    body = (await client.get("/api/cycles/old123old123")).json()

    assert body["status"] == "failed"
    assert body["resumed_as"] == "new456new456"


async def test_the_api_carries_the_trackers_result_on_the_database_answer(web):
    """cost, backend and review decisions live on the tracker: the harness
    read `result` off the database answer, which never had one."""
    client, app = web
    record = _tracked()
    record.result = {"cost_usd": 1.47, "backend": "sdk", "prs": [263]}
    now = datetime.now(timezone.utc)
    await app.state.cycle_repo.save(Cycle(
        id=CycleId(record.id), project_id=record.repo,
        status=CycleStatus.COMPLETED, triggered_by="web",
        started_at=now, completed_at=now,
    ))

    body = (await client.get(f"/api/cycles/{record.id}")).json()

    assert body["result"]["backend"] == "sdk"
    assert body["result"]["cost_usd"] == 1.47
    assert body["resumed_as"] is None


# ── The theater ────────────────────────────────────────────────────────


async def test_the_old_theater_leads_to_the_running_continuation(web):
    client, app = web
    record = _tracked()
    await app.state.cycle_repo.save(_interrupted())
    await app.state.cycle_repo.mark_resumed("old123old123", record.id)

    r = await client.get("/c/old123old123")

    assert r.status_code == 303
    assert r.headers["location"] == f"/swarm/c/{record.id}"


async def test_a_continuation_this_process_forgot_goes_to_the_archive(web):
    client, app = web
    await app.state.cycle_repo.save(_interrupted())
    await app.state.cycle_repo.mark_resumed("old123old123", "gone00gone00")

    r = await client.get("/c/old123old123")

    assert r.status_code == 303
    assert r.headers["location"] == "/swarm/cycles/old123old123"


# ── The resumer ────────────────────────────────────────────────────────


async def test_the_resumer_records_its_trigger_and_the_link(monkeypatch):
    import theswarm.api as api
    from theswarm.application.services.cycle_resumer import ResumePlan, resume_depth
    from theswarm.presentation.web import server

    launched: dict = {}

    async def fake_run(cycle_id, repo, *args, **kwargs):
        launched.update(kwargs, cycle_id=cycle_id)

    monkeypatch.setattr(api, "run_api_cycle", fake_run)

    class Repo:
        marked: list = []

        async def mark_resumed(self, old, new):
            self.marked.append((old, new))

    repo = Repo()
    plan = ResumePlan(cycle_id="old123old123", repo="jrechet/concert-tour-app",
                      resume_from="techlead_breakdown", depth=1)
    app = SimpleNamespace(state=SimpleNamespace())

    await server._launch_resume(app, plan, [], None, repo, None)
    import asyncio
    await asyncio.sleep(0)

    assert launched["triggered_by"] == "auto-resume:1"
    assert resume_depth(launched["triggered_by"]) == 1
    assert launched["resume_cycle_id"] == "old123old123"
    assert repo.marked == [("old123old123", launched["cycle_id"])]


def test_a_cycle_start_records_the_trigger_it_was_given():
    import inspect

    from theswarm.api import _run_api_cycle

    assert inspect.signature(_run_api_cycle).parameters["triggered_by"].default == "web"
    source = inspect.getsource(_run_api_cycle)
    assert 'triggered_by="web"' not in source


# ── The harness ────────────────────────────────────────────────────────


def _harness():
    spec = importlib.util.spec_from_file_location("cycle_e2e_link", ROOT / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scripted(answers):
    calls = []

    def api(path, payload=None):
        calls.append(path)
        return answers.pop(0) if answers else (200, {"status": "running"})

    return api, calls


def test_the_harness_follows_a_resumed_cycle():
    h = _harness()
    api, calls = _scripted([
        (200, {"status": "running"}),
        (0, {"error": "Expecting value"}),          # no container: deploy rolling
        (200, {"status": "failed", "resumed_as": "new456new456"}),
        (200, {"status": "running"}),
        (200, {"status": "completed"}),
    ])

    state, _, final = h.wait_for("old123old123", 600, api=api, sleep=lambda s: None,
                                 health=lambda: True)

    assert (state, final) == ("completed", "new456new456")
    assert calls[-1] == "/api/cycles/new456new456"


def test_a_cycle_the_service_does_not_know_is_lost():
    h = _harness()
    api, _ = _scripted([(404, {"error": "not found"})])

    state, _, final = h.wait_for("nope00nope00", 600, api=api, sleep=lambda s: None,
                                 health=lambda: pytest.fail("a known 404 needs no health wait"))

    assert (state, final) == ("lost", "nope00nope00")


def test_a_service_that_never_comes_back_is_lost():
    h = _harness()
    api, _ = _scripted([(0, {"error": "connection refused"})])

    state, _, _ = h.wait_for("old123old123", 600, api=api, sleep=lambda s: None,
                             health=lambda: False)

    assert state == "lost"


def test_the_hops_are_bounded():
    h = _harness()
    answers = [(200, {"status": "failed", "resumed_as": f"hop{i}"}) for i in range(10)]
    api, _ = _scripted(answers)

    state, _, final = h.wait_for("start", 600, api=api, sleep=lambda s: None,
                                 health=lambda: True)

    assert state == "failed"
    assert final == f"hop{h.MAX_RESUME_HOPS - 1}"
