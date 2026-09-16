"""Tests for the unified cycle route and merged list in routes/api.py.

`GET /api/cycles/{id}` and `GET /api/cycles` read from two stores — the v2
SQLite `CycleRepository` and the in-memory `CycleTracker` — and must present
one unified shape regardless of which store a cycle came from. These tests
exercise that merge with a fake `CycleRepository` (satisfying
`domain/cycles/ports.py`) plus the tracker singleton seeded directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.api import CycleRecord
from theswarm.api import CycleStatus as TrackerCycleStatus
from theswarm.api import get_cycle_tracker
from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus, PhaseStatus
from theswarm.domain.projects.entities import Project
from theswarm.presentation.web.app import create_web_app


class FakeCycleRepository:
    """In-memory `CycleRepository` (domain/cycles/ports.py) for tests."""

    def __init__(self) -> None:
        self._cycles: dict[str, Cycle] = {}

    async def get(self, cycle_id: CycleId) -> Cycle | None:
        return self._cycles.get(str(cycle_id))

    async def list_by_project(self, project_id: str, limit: int = 30) -> list[Cycle]:
        cycles = [c for c in self._cycles.values() if c.project_id == project_id]
        return self._sorted(cycles)[:limit]

    async def list_recent(self, limit: int = 50) -> list[Cycle]:
        return self._sorted(list(self._cycles.values()))[:limit]

    async def save(self, cycle: Cycle) -> None:
        self._cycles[str(cycle.id)] = cycle

    @staticmethod
    def _sorted(cycles: list[Cycle]) -> list[Cycle]:
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        return sorted(cycles, key=lambda c: c.started_at or epoch, reverse=True)


class FakeProjectRepository:
    """Minimal in-memory `ProjectRepository` — unused by these tests beyond wiring."""

    def __init__(self) -> None:
        self._projects: dict[str, Project] = {}

    async def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    async def list_all(self) -> list[Project]:
        return list(self._projects.values())

    async def save(self, project: Project) -> None:
        self._projects[project.id] = project

    async def delete(self, project_id: str) -> None:
        self._projects.pop(project_id, None)


@pytest.fixture(autouse=True)
def _clear_cycle_tracker():
    """The tracker is a module-level singleton — don't let it leak between tests."""
    tracker = get_cycle_tracker()
    tracker._cycles.clear()
    tracker._tasks.clear()
    yield
    tracker._cycles.clear()
    tracker._tasks.clear()


@pytest.fixture
def cycle_repo() -> FakeCycleRepository:
    return FakeCycleRepository()


@pytest.fixture
def project_repo() -> FakeProjectRepository:
    return FakeProjectRepository()


@pytest.fixture
def app(project_repo, cycle_repo):
    return create_web_app(project_repo, cycle_repo, EventBus())


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_cycle(
    cycle_id: str,
    project_id: str = "p1",
    started_at: datetime | None = None,
    status: CycleStatus = CycleStatus.COMPLETED,
    total_cost_usd: float = 0.0,
    with_phase: bool = True,
) -> Cycle:
    phases = ()
    if with_phase:
        phases = (
            PhaseExecution(
                phase="implement",
                agent="dev",
                started_at=started_at or datetime.now(timezone.utc),
                completed_at=started_at or datetime.now(timezone.utc),
                status=PhaseStatus.COMPLETED,
                tokens_used=100,
                cost_usd=0.1,
                summary="did the thing",
            ),
        )
    return Cycle(
        id=CycleId(cycle_id),
        project_id=project_id,
        status=status,
        started_at=started_at,
        total_cost_usd=total_cost_usd,
        phases=phases,
    )


def _seed_tracker_record(
    cycle_id: str,
    repo: str = "o/r",
    issue_number: int | None = None,
    error: str | None = None,
    status: TrackerCycleStatus = TrackerCycleStatus.COMPLETED,
    created_at: str = "2026-01-01T00:00:00",
) -> CycleRecord:
    record = CycleRecord(
        id=cycle_id,
        repo=repo,
        description="",
        callback_url="",
        issue_number=issue_number,
        status=status,
        created_at=created_at,
        error=error,
    )
    get_cycle_tracker()._cycles[cycle_id] = record
    return record


# ── GET /api/cycles/{cycle_id} — unified shape ─────────────────────


class TestUnifiedCycleDetail:
    async def test_sqlite_only_cycle_has_unified_shape(self, client, cycle_repo):
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        await cycle_repo.save(_make_cycle("c-sql", started_at=now, total_cost_usd=4.5))

        r = await client.get("/api/cycles/c-sql")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "c-sql"
        assert data["issue_number"] is None
        assert data["error"] is None
        assert isinstance(data["phases"], list)
        assert len(data["phases"]) == 1
        assert all(isinstance(p, dict) for p in data["phases"])
        assert data["total_cost_usd"] == pytest.approx(4.5)

    async def test_tracker_only_cycle_has_unified_shape(self, client):
        _seed_tracker_record(
            "c-trk", repo="acme/widgets", issue_number=42, error="boom",
            status=TrackerCycleStatus.FAILED,
        )

        r = await client.get("/api/cycles/c-trk")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "c-trk"
        assert data["repo"] == "acme/widgets"
        assert data["issue_number"] == 42
        assert data["error"] == "boom"
        assert data["status"] == "failed"
        assert isinstance(data["phases"], list)

    async def test_cycle_in_both_stores_uses_sqlite_precedence(self, client, cycle_repo):
        now = datetime(2026, 3, 2, tzinfo=timezone.utc)
        await cycle_repo.save(_make_cycle("dup", started_at=now, total_cost_usd=9.99))
        _seed_tracker_record("dup", repo="acme/widgets", issue_number=7, error="oops")

        r = await client.get("/api/cycles/dup")
        assert r.status_code == 200
        data = r.json()
        # Matches the SQLite-only shape: tracker fields are not leaked in.
        assert data["issue_number"] is None
        assert data["error"] is None
        assert data["total_cost_usd"] == pytest.approx(9.99)

    async def test_cycle_absent_from_both_stores_is_404(self, client):
        r = await client.get("/api/cycles/does-not-exist")
        assert r.status_code == 404
        assert r.json() == {"error": "not found"}


# ── GET /api/cycles — merged list ──────────────────────────────────


class TestUnifiedCycleList:
    async def test_cycle_in_both_stores_appears_once(self, client, cycle_repo):
        now = datetime(2026, 3, 2, tzinfo=timezone.utc)
        await cycle_repo.save(_make_cycle("dup", started_at=now))
        _seed_tracker_record("dup", repo="acme/widgets", issue_number=7)

        r = await client.get("/api/cycles")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["cycles"]]
        assert ids.count("dup") == 1

    async def test_merges_both_stores_most_recent_first(self, client, cycle_repo):
        await cycle_repo.save(
            _make_cycle("sql-old", started_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
        )
        await cycle_repo.save(
            _make_cycle("sql-new", started_at=datetime(2024, 6, 1, tzinfo=timezone.utc)),
        )
        _seed_tracker_record("trk-mid", created_at="2024-03-01T00:00:00")
        _seed_tracker_record("trk-newest", created_at="2024-09-01T00:00:00")

        r = await client.get("/api/cycles")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["cycles"]]
        assert ids == ["trk-newest", "sql-new", "trk-mid", "sql-old"]

    async def test_limit_bounds_the_merged_result(self, client, cycle_repo):
        await cycle_repo.save(
            _make_cycle("sql-old", started_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
        )
        await cycle_repo.save(
            _make_cycle("sql-new", started_at=datetime(2024, 6, 1, tzinfo=timezone.utc)),
        )
        _seed_tracker_record("trk-mid", created_at="2024-03-01T00:00:00")
        _seed_tracker_record("trk-newest", created_at="2024-09-01T00:00:00")

        r = await client.get("/api/cycles?limit=2")
        assert r.status_code == 200
        data = r.json()["cycles"]
        assert len(data) == 2
        assert [c["id"] for c in data] == ["trk-newest", "sql-new"]

    async def test_empty_stores_return_empty_list(self, client):
        r = await client.get("/api/cycles")
        assert r.status_code == 200
        assert r.json() == {"cycles": []}
