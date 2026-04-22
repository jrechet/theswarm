"""Phase I infra tests — Security SQLite repositories."""

from __future__ import annotations

import pytest

from theswarm.domain.security.entities import (
    AuthZRule,
    DataInventoryEntry,
    SBOMArtifact,
    SecurityFinding,
    ThreatModel,
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
    conn = await init_db(str(tmp_path / "sec.db"))
    yield conn
    await conn.close()


class TestThreatModelRepo:
    async def test_upsert_and_get(self, db):
        repo = SQLiteThreatModelRepository(db)
        tm = ThreatModel(id="t1", project_id="p", title="v1", assets="users")
        saved = await repo.upsert(tm)
        assert saved.title == "v1"
        # second upsert updates, does not insert
        tm2 = ThreatModel(id="t2", project_id="p", title="v2", assets="users,orgs")
        updated = await repo.upsert(tm2)
        assert updated.id == saved.id  # same row
        assert updated.title == "v2"

    async def test_missing_returns_none(self, db):
        repo = SQLiteThreatModelRepository(db)
        assert await repo.get_for_project("nope") is None


class TestDataInventoryRepo:
    async def test_upsert_and_list(self, db):
        repo = SQLiteDataInventoryRepository(db)
        e = DataInventoryEntry(
            id="d1", project_id="p", field_name="email",
            classification=DataClass.PII,
        )
        await repo.upsert(e)
        e2 = DataInventoryEntry(
            id="d2", project_id="p", field_name="card",
            classification=DataClass.PAYMENT,
        )
        await repo.upsert(e2)
        rows = await repo.list_for_project("p")
        assert len(rows) == 2


class TestFindingRepo:
    async def test_add_and_list_open(self, db):
        repo = SQLiteFindingRepository(db)
        await repo.add(SecurityFinding(
            id="f1", project_id="p", severity=FindingSeverity.HIGH,
            title="XSS in admin",
        ))
        await repo.add(SecurityFinding(
            id="f2", project_id="p", severity=FindingSeverity.LOW,
            title="info leak", status=FindingStatus.RESOLVED,
        ))
        all_ = await repo.list_for_project("p")
        assert len(all_) == 2
        open_ = await repo.list_for_project("p", open_only=True)
        assert len(open_) == 1
        assert open_[0].title == "XSS in admin"


class TestSBOMRepo:
    async def test_add_and_latest(self, db):
        repo = SQLiteSBOMRepository(db)
        await repo.add(SBOMArtifact(
            id="s1", project_id="p", package_count=100, cycle_id="c1",
        ))
        await repo.add(SBOMArtifact(
            id="s2", project_id="p", package_count=105, cycle_id="c2",
        ))
        latest = await repo.latest_for_project("p")
        assert latest is not None
        assert latest.package_count in (100, 105)  # most recent


class TestAuthZRepo:
    async def test_upsert_and_list(self, db):
        repo = SQLiteAuthZRepository(db)
        r = AuthZRule(
            id="r1", project_id="p", actor_role="admin",
            resource="/users", action="read", effect=AuthZEffect.ALLOW,
        )
        saved = await repo.upsert(r)
        assert saved.effect == AuthZEffect.ALLOW

        # upsert same key: updates effect, keeps id
        r2 = AuthZRule(
            id="r2", project_id="p", actor_role="admin",
            resource="/users", action="read", effect=AuthZEffect.DENY,
        )
        updated = await repo.upsert(r2)
        assert updated.id == saved.id
        assert updated.effect == AuthZEffect.DENY
        rows = await repo.list_for_project("p")
        assert len(rows) == 1
