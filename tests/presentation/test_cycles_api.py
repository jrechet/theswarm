"""Tests for the unified cycle shape on GET /api/cycles/{id} and GET /api/cycles.

Uses a fake, in-memory `CycleRepository` (satisfying `domain/cycles/ports.py`)
wired into the app the same way `create_web_app` wires a real one, plus the
module-level `CycleTracker` singleton for tracker-only records.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus, PhaseStatus
from theswarm.presentation.web.app import create_web_app


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


def _sqlite_cycle(cycle_id: str, project_id: str = "p1", *, started_at=None, total_cost_usd=0.0) -> Cycle:
    now = started_at or datetime.now(timezone.utc)
    return Cycle(
        id=CycleId(cycle_id),
        project_id=project_id,
        status=CycleStatus.COMPLETED,
        triggered_by="scheduler",
        started_at=now,
        completed_at=now,
        total_cost_usd=total_cost_usd,
        prs_opened=(3,),
        prs_merged=(),
        phases=(
            PhaseExecution(
                phase="dev",
                agent="dev",
                started_at=now,
                completed_at=now,
                status=PhaseStatus.COMPLETED,
                tokens_used=50,
                cost_usd=0.05,
                summary="did stuff",
            ),
        ),
    )


class TestGetCycleUnifiedShape:
    async def test_sqlite_only_cycle_has_null_issue_number_and_error(self, client, cycle_repo):
        await cycle_repo.save(_sqlite_cycle("sql-only"))

        r = await client.get("/api/cycles/sql-only")
        assert r.status_code == 200
        data = r.json()

        assert data["id"] == "sql-only"
        assert data["issue_number"] is None
        assert data["error"] is None
        assert isinstance(data["phases"], list)
        assert len(data["phases"]) == 1
        assert isinstance(data["phases"][0], dict)
        assert data["phases"][0]["phase"] == "dev"

    async def test_tracker_only_cycle_populates_repo_issue_number_error(self, client):
        from theswarm.api import CycleRequest, get_cycle_tracker
        from theswarm.api import CycleStatus as TrackerStatus

        tracker = get_cycle_tracker()
        record = tracker.create(CycleRequest(repo="owner/repo", issue_number=42))
        tracker.update_status(
            record.id,
            TrackerStatus.FAILED,
            error="boom",
            started_at="2026-01-01T00:00:00",
            completed_at="2026-01-01T00:05:00",
            result={"total_tokens": 100, "cost_usd": 2.5, "prs_opened": [7], "prs_merged": []},
        )

        r = await client.get(f"/api/cycles/{record.id}")
        assert r.status_code == 200
        data = r.json()

        assert data["id"] == record.id
        assert data["repo"] == "owner/repo"
        assert data["issue_number"] == 42
        assert data["error"] == "boom"
        assert data["status"] == "failed"
        assert data["total_cost_usd"] == pytest.approx(2.5)
        assert isinstance(data["phases"], list)

    async def test_known_to_both_stores_matches_sqlite_version(self, client, cycle_repo):
        from theswarm.api import CycleRecord
        from theswarm.api import CycleStatus as TrackerStatus
        from theswarm.api import get_cycle_tracker

        now = datetime.now(timezone.utc)
        await cycle_repo.save(_sqlite_cycle("dup-1", total_cost_usd=9.99, started_at=now))

        tracker = get_cycle_tracker()
        tracker._cycles["dup-1"] = CycleRecord(
            id="dup-1",
            repo="owner/repo",
            description="",
            callback_url="",
            issue_number=99,
            status=TrackerStatus.RUNNING,
            created_at=now.isoformat(),
            error="tracker version should not win",
        )

        r = await client.get("/api/cycles/dup-1")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "completed"
        assert data["total_cost_usd"] == pytest.approx(9.99)
        # SQLite has no notion of issue_number/error — those stay null even
        # though the tracker copy of the same id carries values.
        assert data["issue_number"] is None
        assert data["error"] is None

        listing = await client.get("/api/cycles")
        matches = [c for c in listing.json()["cycles"] if c["id"] == "dup-1"]
        assert len(matches) == 1
        assert matches[0]["total_cost_usd"] == pytest.approx(9.99)

    async def test_absent_from_both_stores_is_404(self, client):
        r = await client.get("/api/cycles/does-not-exist")
        assert r.status_code == 404
        assert r.json() == {"error": "not found"}


class TestListCyclesMergedOrderingAndLimit:
    async def test_merges_most_recent_first(self, client, cycle_repo):
        from theswarm.api import CycleRequest, get_cycle_tracker

        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new = datetime(2026, 6, 1, tzinfo=timezone.utc)
        await cycle_repo.save(_sqlite_cycle("old-sql", started_at=old))
        await cycle_repo.save(_sqlite_cycle("new-sql", started_at=new))
        get_cycle_tracker().create(CycleRequest(repo="owner/repo"))

        r = await client.get("/api/cycles")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["cycles"]]
        assert ids.index("new-sql") < ids.index("old-sql")

    async def test_respects_custom_limit(self, client, cycle_repo):
        for i in range(5):
            await cycle_repo.save(_sqlite_cycle(f"sql-{i}"))

        r = await client.get("/api/cycles?limit=3")
        assert r.status_code == 200
        assert len(r.json()["cycles"]) == 3
