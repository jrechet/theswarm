"""Phase L infrastructure tests — refactor program repo."""

from __future__ import annotations

import pytest

from theswarm.domain.refactor_programs.entities import RefactorProgram
from theswarm.domain.refactor_programs.value_objects import (
    RefactorProgramStatus,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.refactor_programs.program_repo import (
    SQLiteRefactorProgramRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "refactor.db"))
    yield conn
    await conn.close()


class TestRefactorProgramRepo:
    async def test_upsert_preserves_id_on_same_title(self, db):
        repo = SQLiteRefactorProgramRepository(db)
        p1 = RefactorProgram(id="p1", title="migrate auth")
        got1 = await repo.upsert(p1)
        assert got1.id == "p1"

        p2 = RefactorProgram(
            id="p2", title="migrate auth", rationale="clarity",
            status=RefactorProgramStatus.ACTIVE,
        )
        got2 = await repo.upsert(p2)
        assert got2.id == "p1"
        assert got2.rationale == "clarity"
        assert got2.status == RefactorProgramStatus.ACTIVE

    async def test_target_projects_roundtrip(self, db):
        repo = SQLiteRefactorProgramRepository(db)
        p = RefactorProgram(
            id="p1", title="x", target_projects=("a", "b", "c"),
        )
        await repo.upsert(p)
        got = await repo.get_by_title("x")
        assert got is not None
        assert got.target_projects == ("a", "b", "c")

    async def test_list_all_sorted_by_created_desc(self, db):
        repo = SQLiteRefactorProgramRepository(db)
        await repo.upsert(RefactorProgram(id="p1", title="first"))
        await repo.upsert(RefactorProgram(id="p2", title="second"))
        rows = await repo.list_all()
        assert [r.title for r in rows] == ["second", "first"]
