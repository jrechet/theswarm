"""Migration v033 and the Customers repositories (V3 M2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.domain.customers.entities import Customer, Member
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.customer_repo import (
    SQLiteCustomerRepository,
    SQLiteMemberRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteProjectRepository, init_db

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "t.db"))
    yield conn
    await conn.close()


class TestTheMigration:
    async def test_internal_exists_and_projects_belong_to_it(self, db):
        customers = SQLiteCustomerRepository(db)
        internal = await customers.get_by_slug("internal")
        assert internal is not None and internal.id == "internal" and internal.name == "Internal"

        projects = SQLiteProjectRepository(db)
        await projects.save(Project(id="p1", repo=RepoUrl("jrechet/concert-tour-app")))
        (saved,) = await projects.list_all()
        assert saved.customer_id == "internal"
        assert [p.id for p in await projects.list_for_customer("internal")] == ["p1"]

    async def test_a_project_table_from_before_v033_gets_the_column(self, tmp_path):
        """An existing database: the column is added, every row reads internal."""
        import aiosqlite

        path = tmp_path / "old.db"
        async with aiosqlite.connect(str(path)) as old:
            from theswarm.infrastructure.persistence.migrations.v001_initial import SQL
            await old.executescript(SQL)
            await old.execute(
                "INSERT INTO projects (id, repo, created_at, updated_at) VALUES ('p0', 'a/b', '2026-01-01', '2026-01-01')")
            await old.commit()
        conn = await init_db(str(path))
        try:
            (project,) = await SQLiteProjectRepository(conn).list_all()
            assert project.customer_id == "internal"
            conn2 = await init_db(str(path))  # a second boot changes nothing
            await conn2.close()
        finally:
            await conn.close()

    async def test_a_project_moves_to_another_customer(self, db):
        projects = SQLiteProjectRepository(db)
        await SQLiteCustomerRepository(db).save(Customer(id="c1", slug="yakoi", name="Yakoi", created_at=NOW))
        await projects.save(Project(id="p1", repo=RepoUrl("jrechet/yakoi")))
        (project,) = await projects.list_all()
        await projects.save(project.with_customer("c1"))
        assert [p.id for p in await projects.list_for_customer("c1")] == ["p1"]
        assert await projects.list_for_customer("internal") == []


class TestCustomers:
    async def test_roundtrip_and_listing(self, db):
        repo = SQLiteCustomerRepository(db)
        await repo.save(Customer(id="c1", slug="yakoi", name="Yakoi", created_at=NOW))
        await repo.save(Customer(id="c2", slug="maison-verne", name="Maison Verne", created_at=NOW + timedelta(days=1)))
        assert (await repo.get("c1")).name == "Yakoi"
        assert (await repo.get_by_slug("maison-verne")).id == "c2"
        assert [c.slug for c in await repo.list_all()] == ["internal", "yakoi", "maison-verne"]
        await repo.delete("c2")
        assert await repo.get("c2") is None


class TestMembers:
    async def test_roundtrip_and_lookups(self, db):
        await SQLiteCustomerRepository(db).save(Customer(id="c1", slug="yakoi", name="Yakoi", created_at=NOW))
        repo = SQLiteMemberRepository(db)
        nadia = Member(id="m1", customer_id="c1", email="Nadia@Yakoi.fr", display_name="Nadia",
                       github_login="nadiab", invited_at=NOW, invite_token_hash="h1",
                       invite_expires_at=NOW + timedelta(days=14))
        await repo.save(nadia)
        await repo.save(Member(id="m2", customer_id="c1", email="karim@yakoi.fr", invited_at=NOW + timedelta(minutes=1)))

        got = await repo.get("m1")
        assert got.email == "nadia@yakoi.fr" and got.invite_expires_at == NOW + timedelta(days=14)
        assert got.accepted_at is None and got.revoked_at is None
        assert [m.id for m in await repo.list_for_customer("c1")] == ["m1", "m2"]
        assert (await repo.find_by_email("c1", "  NADIA@yakoi.fr ")).id == "m1"
        assert (await repo.find_by_github_login("NadiaB")).id == "m1"
        assert (await repo.find_by_invite_token_hash("h1")).id == "m1"
        assert await repo.find_by_invite_token_hash("") is None

        await repo.save(got.accepted(NOW + timedelta(hours=1)))
        again = await repo.get("m1")
        assert again.is_active and again.invite_token_hash == "" and again.invite_expires_at is None
        assert await repo.find_by_invite_token_hash("h1") is None

        await repo.save(again.revoked(NOW + timedelta(days=3)))
        assert await repo.find_by_github_login("nadiab") is None  # a revoked member has no door

    async def test_one_row_per_email_per_customer(self, db):
        import aiosqlite

        await SQLiteCustomerRepository(db).save(Customer(id="c1", slug="yakoi", name="Yakoi", created_at=NOW))
        repo = SQLiteMemberRepository(db)
        await repo.save(Member(id="m1", customer_id="c1", email="nadia@yakoi.fr", invited_at=NOW))
        with pytest.raises(aiosqlite.IntegrityError):
            await repo.save(Member(id="m9", customer_id="c1", email="nadia@yakoi.fr", invited_at=NOW))
