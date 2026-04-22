"""Phase I application tests — Security services."""

from __future__ import annotations

import pytest

from theswarm.application.services.security import (
    AuthZService,
    DataInventoryService,
    SBOMService,
    SecurityFindingService,
    ThreatModelService,
)
from theswarm.domain.security.value_objects import (
    AuthZEffect,
    DataClass,
    FindingSeverity,
    FindingStatus,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.security import (
    SQLiteAuthZRepository,
    SQLiteDataInventoryRepository,
    SQLiteFindingRepository,
    SQLiteSBOMRepository,
    SQLiteThreatModelRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "secsvc.db"))
    yield conn
    await conn.close()


class TestThreatModelService:
    async def test_upsert_preserves_id_on_update(self, db):
        svc = ThreatModelService(SQLiteThreatModelRepository(db))
        tm1 = await svc.upsert("p", title="v1", assets="a")
        tm2 = await svc.upsert("p", title="v2", assets="a,b")
        assert tm1.id == tm2.id
        assert tm2.title == "v2"


class TestDataInventoryService:
    async def test_upsert_and_list_sorted_by_class(self, db):
        svc = DataInventoryService(SQLiteDataInventoryRepository(db))
        await svc.upsert("p", field_name="email", classification=DataClass.PII)
        await svc.upsert(
            "p", field_name="label", classification=DataClass.PUBLIC,
        )
        rows = await svc.list("p")
        assert len(rows) == 2


class TestSecurityFindingService:
    async def test_open_triage_resolve(self, db):
        svc = SecurityFindingService(SQLiteFindingRepository(db))
        f = await svc.open(
            "p", severity=FindingSeverity.HIGH, title="SSRF in webhook",
        )
        assert f.status == FindingStatus.OPEN
        await svc.triage(f.id, note="assigned to sec")
        await svc.resolve(f.id, note="patched in #123")

        all_ = await svc.list("p")
        assert len(all_) == 1
        assert all_[0].status == FindingStatus.RESOLVED
        assert all_[0].resolution_note == "patched in #123"

        open_ = await svc.list("p", open_only=True)
        assert len(open_) == 0

    async def test_suppress(self, db):
        svc = SecurityFindingService(SQLiteFindingRepository(db))
        f = await svc.open(
            "p", severity=FindingSeverity.LOW, title="low",
        )
        await svc.suppress(f.id, note="false positive")
        rows = await svc.list("p")
        assert rows[0].status == FindingStatus.SUPPRESSED


class TestSBOMService:
    async def test_record_and_latest(self, db):
        svc = SBOMService(SQLiteSBOMRepository(db))
        a = await svc.record(
            "p", tool="syft", package_count=42, license_summary="MIT:30;Apache:12",
        )
        assert a.package_count == 42
        latest = await svc.latest("p")
        assert latest is not None
        assert latest.package_count == 42


class TestAuthZService:
    async def test_upsert_then_flip_effect(self, db):
        svc = AuthZService(SQLiteAuthZRepository(db))
        r1 = await svc.upsert(
            "p", actor_role="admin", resource="/users", action="read",
            effect=AuthZEffect.ALLOW,
        )
        r2 = await svc.upsert(
            "p", actor_role="admin", resource="/users", action="read",
            effect=AuthZEffect.DENY, notes="tightened after audit",
        )
        assert r1.id == r2.id
        assert r2.effect == AuthZEffect.DENY

        rows = await svc.list("p")
        assert len(rows) == 1

    async def test_delete(self, db):
        svc = AuthZService(SQLiteAuthZRepository(db))
        r = await svc.upsert(
            "p", actor_role="admin", resource="/x", action="read",
        )
        await svc.delete(r.id)
        assert await svc.list("p") == []
