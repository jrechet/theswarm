"""Phase L application tests — refactor programs service."""

from __future__ import annotations

import pytest

from theswarm.application.services.refactor_programs import (
    RefactorProgramService,
)
from theswarm.domain.refactor_programs.value_objects import (
    RefactorProgramStatus,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.refactor_programs.program_repo import (
    SQLiteRefactorProgramRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "refactor_svc.db"))
    yield conn
    await conn.close()


class TestRefactorProgramService:
    async def test_upsert_dedupes_projects(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        p = await svc.upsert(
            title="migrate auth",
            target_projects=("a", "b", "a", " ", "b", "c"),
        )
        assert p.target_projects == ("a", "b", "c")

    async def test_activate_sets_started_at(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        await svc.upsert(title="t")
        p = await svc.activate("t")
        assert p.status == RefactorProgramStatus.ACTIVE
        assert p.started_at is not None

    async def test_complete_sets_completed_at(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        await svc.upsert(title="t")
        await svc.activate("t")
        p = await svc.complete("t")
        assert p.status == RefactorProgramStatus.COMPLETED
        assert p.completed_at is not None
        assert p.is_terminal

    async def test_cancel_marks_terminal(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        await svc.upsert(title="t")
        p = await svc.cancel("t")
        assert p.status == RefactorProgramStatus.CANCELLED
        assert p.is_terminal

    async def test_add_and_remove_project(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        await svc.upsert(title="t", target_projects=("a",))
        p = await svc.add_project("t", "b")
        assert p.target_projects == ("a", "b")
        p = await svc.add_project("t", "a")  # duplicate noop
        assert p.target_projects == ("a", "b")
        p = await svc.remove_project("t", "a")
        assert p.target_projects == ("b",)

    async def test_activate_missing_raises(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        with pytest.raises(ValueError):
            await svc.activate("missing")

    async def test_complete_missing_raises(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        with pytest.raises(ValueError):
            await svc.complete("missing")

    async def test_add_project_missing_raises(self, db):
        svc = RefactorProgramService(SQLiteRefactorProgramRepository(db))
        with pytest.raises(ValueError):
            await svc.add_project("missing", "p")
