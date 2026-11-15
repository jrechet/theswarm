"""The theater's resume button posts to V3 (pre-M6): a failed cycle with a
good checkpoint is continued under a new tracker record, and the
continuation opens in the theater; one with nothing to resume from goes
back to its theater, nothing started.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.presentation.test_cycle_resume import _seed_failed_cycle, db  # noqa: F401 — the fixture
from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCheckpointRepository,
    SQLiteCycleRepository,
    SQLiteProjectRepository,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture(autouse=True)
def _isolate_tracker():
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    tracker._cycles.clear()
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)


def _app(db):
    return create_web_app(SQLiteProjectRepository(db), SQLiteCycleRepository(db), EventBus(), SSEHub(),
                          checkpoint_repo=SQLiteCheckpointRepository(db), base_path="/swarm")


async def test_a_resumable_cycle_is_continued_and_the_theater_opens_on_it(db, _isolate_tracker):
    cycle = await _seed_failed_cycle(db, "cyc-v3-res", "qa")
    app = _app(db)
    with patch("theswarm.api.run_api_cycle", new=AsyncMock(return_value=None)) as run:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/cycles/{cycle.id}/resume")  # the app serves at the root; the prefix is for the links
    assert r.status_code == 303
    records = [rec for rec in _isolate_tracker.list_recent(limit=10) if rec.description.startswith("Resume of")]
    assert len(records) == 1 and records[0].description == f"Resume of {cycle.id} from qa"
    assert r.headers["location"] == f"/swarm/cycles/{records[0].id}"  # the continuation's theater, not V1's page
    # The run is a task the route creates; the call (and its arguments) is recorded at once.
    assert run.call_count == 1 and run.call_args.kwargs["resume_from"] == "qa"


async def test_the_continuation_runs_on_the_cycle_s_own_graph_thread_for_its_feature(db, _isolate_tracker):
    """The button passed no thread: the continuation looked for a checkpoint
    under its own new id, found none, and died on CycleNotResumable — and it
    had forgotten the feature (the review of 2026-11-11)."""
    from theswarm.domain.cycles.entities import Cycle
    from theswarm.domain.cycles.value_objects import CycleId, CycleStatus

    repo = SQLiteCycleRepository(db)
    failed = await _seed_failed_cycle(db, "cyc-v3-quota", "dev_loop")
    await repo.save(Cycle(id=CycleId("cyc-v3-quota"), project_id="jrechet/concert-tour-app",
                          status=CycleStatus.FAILED, started_at=failed.started_at, issue_number=840))
    app = _app(db)
    with patch("theswarm.api.run_api_cycle", new=AsyncMock(return_value=None)) as run:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/cycles/cyc-v3-quota/resume")
            again = await c.post("/cycles/cyc-v3-quota/resume")  # a second click: the continuation, not a second one
    kwargs = run.call_args.kwargs
    assert kwargs["resume_cycle_id"] == "cyc-v3-quota" and kwargs["issue_number"] == 840
    assert kwargs["triggered_by"] == "resume" and run.call_count == 1
    [record] = [rec for rec in _isolate_tracker.list_recent(limit=10) if rec.description.startswith("Resume of")]
    assert record.issue_number == 840
    assert (await repo.get(CycleId("cyc-v3-quota"))).resumed_as == record.id  # /cycles/{old} follows it
    assert r.headers["location"] == again.headers["location"] == f"/swarm/cycles/{record.id}"


async def test_a_continuation_that_failed_resumes_on_its_origin_s_thread(db, _isolate_tracker):
    from theswarm.domain.cycles.value_objects import CycleId

    repo = SQLiteCycleRepository(db)
    await _seed_failed_cycle(db, "cyc-origin", "qa")
    await _seed_failed_cycle(db, "cyc-second", "qa")
    await repo.mark_resumed("cyc-origin", "cyc-second")  # a deploy interrupted the origin; this one went on
    app = _app(db)
    with patch("theswarm.api.run_api_cycle", new=AsyncMock(return_value=None)) as run:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/cycles/cyc-second/resume")
    assert run.call_args.kwargs["resume_cycle_id"] == "cyc-origin"
    assert (await repo.get(CycleId("cyc-second"))).resumed_as


async def test_a_cycle_already_continued_offers_no_resume(db, _isolate_tracker):
    from unittest.mock import AsyncMock as Mock

    repo = SQLiteCycleRepository(db)
    await _seed_failed_cycle(db, "cyc-done-res", "qa")
    await repo.mark_resumed("cyc-done-res", "cyc-next")
    app = _app(db)
    with patch("theswarm.application.services.pinned_issue.load_pinned_issue", Mock()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            page = await c.get("/cycles/cyc-done-res", headers={"accept": "text/html"})
    assert 'data-testid="resume"' not in page.text


async def test_nothing_to_resume_from_goes_back_to_the_theater(db, _isolate_tracker):
    cycle = await _seed_failed_cycle(db, "cyc-v3-none", None)
    app = _app(db)
    with patch("theswarm.api.run_api_cycle", new=AsyncMock(return_value=None)) as run:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/cycles/{cycle.id}/resume")  # the app serves at the root; the prefix is for the links
    assert r.status_code == 303 and r.headers["location"] == f"/swarm/cycles/{cycle.id}"
    assert run.call_count == 0 and not _isolate_tracker.list_recent(limit=10)


async def test_a_paused_cycle_resumes_on_its_thread_whatever_phase_it_stopped_before(db, _isolate_tracker):
    """A3.2: a pause taken before the first phase finished leaves no phase
    checkpoint to name; the graph thread is what a paused cycle resumes from."""
    from datetime import datetime, timezone

    from theswarm.domain.cycles.entities import Cycle
    from theswarm.domain.cycles.value_objects import CycleId, CycleStatus

    repo = SQLiteCycleRepository(db)
    await repo.save(Cycle(id=CycleId("cyc-paused"), project_id="jrechet/concert-tour-app",
                          status=CycleStatus.PAUSED, started_at=datetime.now(timezone.utc), issue_number=905))
    app = _app(db)
    with patch("theswarm.api.run_api_cycle", new=AsyncMock(return_value=None)) as run:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/cycles/cyc-paused/resume")
    kwargs = run.call_args.kwargs
    assert kwargs["resume_cycle_id"] == "cyc-paused" and kwargs["issue_number"] == 905
    [record] = [rec for rec in _isolate_tracker.list_recent(limit=10) if rec.description.startswith("Resume of")]
    assert record.description == "Resume of cyc-paused from its pause"
    assert r.headers["location"] == f"/swarm/cycles/{record.id}"
    assert (await repo.get(CycleId("cyc-paused"))).resumed_as == record.id
