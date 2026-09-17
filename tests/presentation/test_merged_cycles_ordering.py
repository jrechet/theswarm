"""Chronological ordering of `_list_merged_cycles` across the SQLite/tracker split.

`_list_merged_cycles` (src/theswarm/presentation/web/routes/api.py, exercised
here through `GET /api/cycles`) merges `CycleDTO`s from the SQLite-backed
`ListCyclesQuery` with `CycleRecord`s from the in-memory `CycleTracker` and
sorts the combination by `started_at`. SQLite always hands back an aware UTC
ISO string; the tracker can still hand back a naive one. Comparing the two as
raw strings sorts lexicographically, not chronologically: a naive string with
"bigger" digits can still represent an *earlier* UTC instant than an aware
one, depending on what local offset it's actually in. `_cycle_sort_key`
resolves this by parsing both into aware UTC datetimes before sorting — a
naive value is interpreted via `datetime.astimezone()`, which reads the
system's local timezone. These tests pin the system TZ explicitly (via
`time.tzset()`) so both directions can be constructed deterministically: the
same naive clock reading, five minutes past the SQLite fixture's digits,
represents a *later* UTC instant under one offset and an *earlier* one under
another.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.presentation.web.app import create_web_app

pytestmark = pytest.mark.skipif(
    not hasattr(time, "tzset"), reason="time.tzset() is POSIX-only"
)


class FakeCycleRepository:
    """In-memory `CycleRepository` (see `domain/cycles/ports.py`)."""

    def __init__(self) -> None:
        self._cycles: dict[str, Cycle] = {}

    async def get(self, cycle_id: CycleId) -> Cycle | None:
        return self._cycles.get(str(cycle_id))

    async def list_by_project(self, project_id: str, limit: int = 30) -> list[Cycle]:
        cycles = [c for c in self._cycles.values() if c.project_id == project_id]
        cycles.sort(key=lambda c: c.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return cycles[:limit]

    async def list_recent(self, limit: int = 50) -> list[Cycle]:
        cycles = list(self._cycles.values())
        cycles.sort(key=lambda c: c.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return cycles[:limit]

    async def save(self, cycle: Cycle) -> None:
        self._cycles[str(cycle.id)] = cycle


class FakeProjectRepository:
    """Empty `ProjectRepository` — these tests never touch projects."""

    async def get(self, project_id: str):
        return None

    async def list_all(self):
        return []

    async def save(self, project) -> None:
        pass

    async def delete(self, project_id: str) -> None:
        pass


@pytest.fixture(autouse=True)
def _clear_cycle_tracker():
    """The module-level CycleTracker singleton must not leak between tests."""
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    tracker._cycles.clear()
    tracker._tasks.clear()
    yield
    tracker._cycles.clear()
    tracker._tasks.clear()


@pytest.fixture
def local_tz(monkeypatch):
    """Pin the process's local timezone so naive-timestamp interpretation is deterministic.

    Restores the original `TZ` afterwards so other tests in the suite (which
    may assume the runner's real timezone) are unaffected.
    """
    original = os.environ.get("TZ")

    def _set(posix_tz: str) -> None:
        monkeypatch.setenv("TZ", posix_tz)
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


@pytest.fixture
def cycle_repo():
    return FakeCycleRepository()


@pytest.fixture
def app(cycle_repo):
    return create_web_app(FakeProjectRepository(), cycle_repo, EventBus())


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _sqlite_cycle(cycle_id: str, started_at: datetime, project_id: str = "p1") -> Cycle:
    return Cycle(
        id=CycleId(cycle_id),
        project_id=project_id,
        status=CycleStatus.COMPLETED,
        triggered_by="scheduler",
        started_at=started_at,
        completed_at=started_at,
    )


def _tracker_record_with_started_at(started_at_naive: str | None):
    """Create a tracker `CycleRecord` and set its `started_at` to a raw string."""
    from theswarm.api import CycleRequest, get_cycle_tracker

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/repo"))
    tracker.update_status(record.id, record.status, started_at=started_at_naive or "")
    return record.id


# SQLite fixture shared by both direction tests: an aware UTC ISO string.
_SQLITE_STARTED_AT = datetime(2026, 9, 16, 13, 7, 49, tzinfo=timezone.utc)
# The tracker's naive clock reading: literally 5 minutes past the SQLite
# fixture's digits, with no offset attached — its actual UTC instant depends
# entirely on which local timezone it's interpreted under.
_TRACKER_STARTED_AT_NAIVE = "2026-09-16T13:12:49"


async def test_tracker_cycle_newer_in_utc_sorts_first(client, cycle_repo, local_tz):
    # Local = UTC-5: the naive tracker reading resolves to 2026-09-16T18:12:49+00:00,
    # after the SQLite fixture's 13:07:49+00:00.
    local_tz("Etc/GMT+5")

    await cycle_repo.save(_sqlite_cycle("sql-cycle", _SQLITE_STARTED_AT))
    tracker_id = _tracker_record_with_started_at(_TRACKER_STARTED_AT_NAIVE)

    r = await client.get("/api/cycles")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["cycles"]]
    assert ids.index(tracker_id) < ids.index("sql-cycle")


async def test_sqlite_cycle_newer_in_utc_sorts_first(client, cycle_repo, local_tz):
    # Local = UTC+8: the same naive tracker reading resolves to
    # 2026-09-16T05:12:49+00:00, before the SQLite fixture's 13:07:49+00:00 —
    # even though its naive digits ("13:12:49") look later than the SQLite
    # fixture's ("13:07:49"). A raw string comparison would get this backwards.
    local_tz("Etc/GMT-8")

    await cycle_repo.save(_sqlite_cycle("sql-cycle", _SQLITE_STARTED_AT))
    tracker_id = _tracker_record_with_started_at(_TRACKER_STARTED_AT_NAIVE)

    r = await client.get("/api/cycles")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["cycles"]]
    assert ids.index("sql-cycle") < ids.index(tracker_id)


async def test_cycle_with_no_timestamp_sorts_last_and_does_not_raise(client, cycle_repo, local_tz):
    local_tz("UTC")

    await cycle_repo.save(_sqlite_cycle("sql-cycle", _SQLITE_STARTED_AT))
    await cycle_repo.save(_sqlite_cycle("sql-timeless", started_at=None))

    r = await client.get("/api/cycles")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()["cycles"]]
    assert ids[-1] == "sql-timeless"
    assert ids.index("sql-cycle") < ids.index("sql-timeless")
