"""Phase I infra tests — SRE SQLite repositories."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.sre.entities import CostSample, Deployment, Incident
from theswarm.domain.sre.value_objects import (
    CostSource,
    DeployStatus,
    IncidentSeverity,
    IncidentStatus,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.sre import (
    SQLiteCostRepository,
    SQLiteDeploymentRepository,
    SQLiteIncidentRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "sre.db"))
    yield conn
    await conn.close()


class TestDeploymentRepo:
    async def test_add_update_list(self, db):
        repo = SQLiteDeploymentRepository(db)
        d = Deployment(id="d1", project_id="p", environment="prod", version="1.0")
        await repo.add(d)
        await repo.update_status(
            "d1", DeployStatus.SUCCESS,
            datetime.now(timezone.utc), notes="ok",
        )
        got = await repo.get("d1")
        assert got is not None
        assert got.status == DeployStatus.SUCCESS
        assert got.notes == "ok"
        assert len(await repo.list_for_project("p")) == 1


class TestIncidentRepo:
    async def test_add_update_with_timeline(self, db):
        repo = SQLiteIncidentRepository(db)
        i = Incident(
            id="i1", project_id="p", title="500s",
            severity=IncidentSeverity.SEV1,
            timeline=("12:00 detected", "12:05 rolled back"),
        )
        await repo.add(i)
        got = await repo.get("i1")
        assert got is not None
        assert got.timeline == ("12:00 detected", "12:05 rolled back")

        from dataclasses import replace
        resolved = replace(
            got, status=IncidentStatus.RESOLVED,
            resolved_at=datetime.now(timezone.utc),
            timeline=got.timeline + ("12:20 resolved",),
            postmortem="rate limit fix deployed",
        )
        await repo.update(resolved)
        reloaded = await repo.get("i1")
        assert reloaded is not None
        assert reloaded.status == IncidentStatus.RESOLVED
        assert len(reloaded.timeline) == 3
        assert reloaded.postmortem == "rate limit fix deployed"

    async def test_open_only_filter(self, db):
        repo = SQLiteIncidentRepository(db)
        await repo.add(Incident(
            id="i1", project_id="p", title="a",
            severity=IncidentSeverity.SEV3, status=IncidentStatus.OPEN,
        ))
        await repo.add(Incident(
            id="i2", project_id="p", title="b",
            severity=IncidentSeverity.SEV3, status=IncidentStatus.RESOLVED,
        ))
        open_ = await repo.list_for_project("p", open_only=True)
        assert len(open_) == 1


class TestCostRepo:
    async def test_add_and_rollup(self, db):
        repo = SQLiteCostRepository(db)
        await repo.add(CostSample(
            id="c1", project_id="p", source=CostSource.AI, amount_usd=2.5,
        ))
        await repo.add(CostSample(
            id="c2", project_id="p", source=CostSource.AI, amount_usd=1.0,
        ))
        await repo.add(CostSample(
            id="c3", project_id="p", source=CostSource.INFRA, amount_usd=10.0,
        ))
        rollup = await repo.rollup_by_source("p")
        assert rollup["ai"] == 3.5
        assert rollup["infra"] == 10.0
