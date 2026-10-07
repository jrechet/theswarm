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


async def test_nothing_to_resume_from_goes_back_to_the_theater(db, _isolate_tracker):
    cycle = await _seed_failed_cycle(db, "cyc-v3-none", None)
    app = _app(db)
    with patch("theswarm.api.run_api_cycle", new=AsyncMock(return_value=None)) as run:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(f"/cycles/{cycle.id}/resume")  # the app serves at the root; the prefix is for the links
    assert r.status_code == 303 and r.headers["location"] == f"/swarm/cycles/{cycle.id}"
    assert run.call_count == 0 and not _isolate_tracker.list_recent(limit=10)
