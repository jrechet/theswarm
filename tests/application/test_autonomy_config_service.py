"""Phase L application tests — autonomy config service."""

from __future__ import annotations

import pytest

from theswarm.application.services.autonomy_config import (
    AutonomyConfigService,
)
from theswarm.domain.autonomy_config.value_objects import AutonomyLevel
from theswarm.infrastructure.autonomy_config.config_repo import (
    SQLiteAutonomyConfigRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "autonomy_svc.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def svc(db):
    return AutonomyConfigService(SQLiteAutonomyConfigRepository(db))


class TestAutonomyConfigService:
    async def test_set_level_creates_config(self, svc):
        c = await svc.set_level(
            project_id="p1", role="dev",
            level=AutonomyLevel.AUTONOMOUS,
            note="trusted", actor="alice",
        )
        assert c.level == AutonomyLevel.AUTONOMOUS
        assert c.note == "trusted"
        assert c.updated_by == "alice"

    async def test_set_level_updates_existing(self, svc):
        await svc.set_level(
            project_id="p1", role="dev", level=AutonomyLevel.MANUAL,
        )
        updated = await svc.set_level(
            project_id="p1", role="dev", level=AutonomyLevel.AUTONOMOUS,
        )
        assert updated.level == AutonomyLevel.AUTONOMOUS
        rows = await svc.list_for_project("p1")
        assert len(rows) == 1

    async def test_get_returns_none_when_missing(self, svc):
        got = await svc.get("p1", "dev")
        assert got is None

    async def test_list_for_project_empty(self, svc):
        rows = await svc.list_for_project("p1")
        assert rows == []

    async def test_list_all_across_projects(self, svc):
        await svc.set_level(
            project_id="p1", role="dev", level=AutonomyLevel.MANUAL,
        )
        await svc.set_level(
            project_id="p2", role="qa", level=AutonomyLevel.AUTONOMOUS,
        )
        rows = await svc.list_all()
        assert len(rows) == 2
        pairs = {(r.project_id, r.role) for r in rows}
        assert pairs == {("p1", "dev"), ("p2", "qa")}
