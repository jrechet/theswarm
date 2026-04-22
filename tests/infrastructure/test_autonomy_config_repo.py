"""Phase L infra tests — autonomy config repo."""

from __future__ import annotations

import pytest

from theswarm.domain.autonomy_config.entities import AutonomyConfig
from theswarm.domain.autonomy_config.value_objects import AutonomyLevel
from theswarm.infrastructure.autonomy_config.config_repo import (
    SQLiteAutonomyConfigRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "autonomy.db"))
    yield conn
    await conn.close()


class TestAutonomyConfigRepo:
    async def test_upsert_and_get(self, db):
        repo = SQLiteAutonomyConfigRepository(db)
        cfg = AutonomyConfig(
            id="c1", project_id="p1", role="dev",
            level=AutonomyLevel.AUTONOMOUS, note="trusted",
        )
        await repo.upsert(cfg)
        got = await repo.get("p1", "dev")
        assert got is not None
        assert got.level == AutonomyLevel.AUTONOMOUS
        assert got.note == "trusted"

    async def test_upsert_replaces_same_project_role(self, db):
        repo = SQLiteAutonomyConfigRepository(db)
        await repo.upsert(AutonomyConfig(
            id="c1", project_id="p1", role="dev",
            level=AutonomyLevel.MANUAL,
        ))
        await repo.upsert(AutonomyConfig(
            id="c2", project_id="p1", role="dev",
            level=AutonomyLevel.AUTONOMOUS,
        ))
        rows = await repo.list_for_project("p1")
        assert len(rows) == 1
        assert rows[0].level == AutonomyLevel.AUTONOMOUS
        # id preserved from first insert
        assert rows[0].id == "c1"

    async def test_list_for_project_isolates(self, db):
        repo = SQLiteAutonomyConfigRepository(db)
        await repo.upsert(AutonomyConfig(
            id="c1", project_id="p1", role="dev",
        ))
        await repo.upsert(AutonomyConfig(
            id="c2", project_id="p2", role="dev",
        ))
        rows = await repo.list_for_project("p1")
        assert len(rows) == 1
        assert rows[0].project_id == "p1"

    async def test_list_for_project_sorted_by_role(self, db):
        repo = SQLiteAutonomyConfigRepository(db)
        await repo.upsert(AutonomyConfig(
            id="c1", project_id="p1", role="zeta",
        ))
        await repo.upsert(AutonomyConfig(
            id="c2", project_id="p1", role="alpha",
        ))
        rows = await repo.list_for_project("p1")
        assert [r.role for r in rows] == ["alpha", "zeta"]
