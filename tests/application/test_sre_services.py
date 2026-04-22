"""Phase I application tests — SRE services."""

from __future__ import annotations

import pytest

from theswarm.application.services.sre import (
    CostService,
    DeploymentService,
    IncidentService,
)
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
    conn = await init_db(str(tmp_path / "sresvc.db"))
    yield conn
    await conn.close()


class TestDeploymentService:
    async def test_start_then_succeed(self, db):
        svc = DeploymentService(SQLiteDeploymentRepository(db))
        d = await svc.start("p", version="1.2.3", triggered_by="sre")
        assert d.status == DeployStatus.IN_PROGRESS
        await svc.succeed(d.id, notes="green")
        got = await svc.get(d.id)
        assert got is not None
        assert got.status == DeployStatus.SUCCESS
        assert got.notes == "green"

    async def test_rollback(self, db):
        svc = DeploymentService(SQLiteDeploymentRepository(db))
        d = await svc.start("p", version="1.2.4")
        await svc.rollback(d.id, notes="bad migration")
        got = await svc.get(d.id)
        assert got is not None
        assert got.status == DeployStatus.ROLLED_BACK


class TestIncidentService:
    async def test_full_lifecycle(self, db):
        svc = IncidentService(SQLiteIncidentRepository(db))
        i = await svc.open(
            "p", title="5xx spike",
            severity=IncidentSeverity.SEV1, summary="error rate 10%",
        )
        assert i.status == IncidentStatus.OPEN
        assert len(i.timeline) == 1

        await svc.triage(i.id, note="oncall engaged")
        await svc.add_timeline(i.id, note="rolled back image")
        mitigated = await svc.mitigate(i.id, note="error rate < 1%")
        assert mitigated.status == IncidentStatus.MITIGATED
        assert mitigated.mitigated_at is not None

        resolved = await svc.resolve(i.id, note="clean for 30 min")
        assert resolved.status == IncidentStatus.RESOLVED
        assert resolved.resolved_at is not None

        done = await svc.write_postmortem(
            i.id, postmortem="Root cause: unbounded query; added LIMIT",
        )
        assert done.status == IncidentStatus.POSTMORTEM_DONE
        assert "unbounded" in done.postmortem
        # Timeline now has: detected, triaged, rolled back, mitigated, resolved
        assert len(done.timeline) == 5

    async def test_open_only_filter(self, db):
        svc = IncidentService(SQLiteIncidentRepository(db))
        a = await svc.open("p", title="a", severity=IncidentSeverity.SEV3)
        b = await svc.open("p", title="b", severity=IncidentSeverity.SEV3)
        await svc.resolve(b.id)
        open_ = await svc.list("p", open_only=True)
        assert len(open_) == 1
        assert open_[0].id == a.id

    async def test_missing_incident_raises(self, db):
        svc = IncidentService(SQLiteIncidentRepository(db))
        with pytest.raises(ValueError):
            await svc.mitigate("no-such-id")


class TestCostService:
    async def test_record_and_rollup(self, db):
        svc = CostService(SQLiteCostRepository(db))
        await svc.record("p", source=CostSource.AI, amount_usd=4.20)
        await svc.record("p", source=CostSource.INFRA, amount_usd=12.50)
        roll = await svc.rollup("p")
        assert roll["ai"] == 4.20
        assert roll["infra"] == 12.50
