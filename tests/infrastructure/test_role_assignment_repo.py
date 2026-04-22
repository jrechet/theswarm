"""Tests for SQLiteRoleAssignmentRepository + migration v006."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.agents.entities import PORTFOLIO_PROJECT_ID, RoleAssignment
from theswarm.domain.agents.value_objects import AgentRole
from theswarm.infrastructure.agents.role_assignment_repo import (
    SQLiteRoleAssignmentRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    yield conn
    await conn.close()


def _mk(role: AgentRole, codename: str, project_id: str = "demo") -> RoleAssignment:
    return RoleAssignment(
        id=RoleAssignment.new_id(),
        project_id=project_id,
        role=role,
        codename=codename,
    )


class TestSQLiteRoleAssignmentRepository:
    async def test_save_and_get(self, db):
        repo = SQLiteRoleAssignmentRepository(db)
        a = _mk(AgentRole.PO, "Mei")
        await repo.save(a)

        loaded = await repo.get(a.id)
        assert loaded is not None
        assert loaded.codename == "Mei"
        assert loaded.role == AgentRole.PO
        assert loaded.project_id == "demo"
        assert loaded.is_active is True

    async def test_find_active(self, db):
        repo = SQLiteRoleAssignmentRepository(db)
        await repo.save(_mk(AgentRole.DEV, "Aarav"))

        found = await repo.find("demo", AgentRole.DEV)
        assert found is not None
        assert found.codename == "Aarav"

    async def test_find_ignores_retired(self, db):
        repo = SQLiteRoleAssignmentRepository(db)
        a = _mk(AgentRole.DEV, "Aarav")
        await repo.save(a)
        await repo.save(a.retire(at=datetime(2026, 1, 1, tzinfo=timezone.utc)))

        assert await repo.find("demo", AgentRole.DEV) is None

    async def test_list_for_project_filters_by_project(self, db):
        repo = SQLiteRoleAssignmentRepository(db)
        await repo.save(_mk(AgentRole.PO, "Mei", project_id="a"))
        await repo.save(_mk(AgentRole.PO, "Ines", project_id="b"))

        a_roster = await repo.list_for_project("a")
        assert [x.codename for x in a_roster] == ["Mei"]

    async def test_list_all(self, db):
        repo = SQLiteRoleAssignmentRepository(db)
        await repo.save(_mk(AgentRole.PO, "Mei", project_id="a"))
        await repo.save(
            _mk(AgentRole.SCOUT, "Kenji", project_id=PORTFOLIO_PROJECT_ID),
        )
        all_rows = await repo.list_all()
        assert {r.codename for r in all_rows} == {"Mei", "Kenji"}

    async def test_codenames_in_use_excludes_retired(self, db):
        repo = SQLiteRoleAssignmentRepository(db)
        a = _mk(AgentRole.PO, "Mei")
        await repo.save(a)
        await repo.save(_mk(AgentRole.DEV, "Aarav"))
        await repo.save(a.retire())

        in_use = await repo.codenames_in_use()
        assert in_use == {"Aarav"}

    async def test_codename_unique_index(self, db):
        """The unique index on codename means only one active row per name.

        ``INSERT OR REPLACE`` deletes the conflicting row before inserting,
        so after a collision the later assignment wins. The service layer
        avoids collisions by checking ``codenames_in_use`` before picking.
        """
        repo = SQLiteRoleAssignmentRepository(db)
        await repo.save(_mk(AgentRole.PO, "Mei", project_id="a"))
        await repo.save(_mk(AgentRole.DEV, "Mei", project_id="b"))
        all_rows = await repo.list_all()
        codenames = [r.codename for r in all_rows]
        assert codenames.count("Mei") == 1
