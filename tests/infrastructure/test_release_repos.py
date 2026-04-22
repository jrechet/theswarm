"""Phase J infrastructure tests — Release repos."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.release.entities import (
    FeatureFlag,
    ReleaseVersion,
    RollbackAction,
)
from theswarm.domain.release.value_objects import (
    FlagState,
    ReleaseStatus,
    RollbackStatus,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.release.flag_repo import (
    SQLiteFeatureFlagRepository,
)
from theswarm.infrastructure.release.rollback_repo import (
    SQLiteRollbackActionRepository,
)
from theswarm.infrastructure.release.version_repo import (
    SQLiteReleaseVersionRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "release.db"))
    yield conn
    await conn.close()


class TestReleaseVersionRepo:
    async def test_upsert_preserves_id(self, db):
        repo = SQLiteReleaseVersionRepository(db)
        v1 = ReleaseVersion(
            id="v1", project_id="p", version="1.0.0",
        )
        got1 = await repo.upsert(v1)
        v2 = ReleaseVersion(
            id="v2", project_id="p", version="1.0.0",
            status=ReleaseStatus.RELEASED,
            released_at=datetime.now(timezone.utc),
        )
        got2 = await repo.upsert(v2)
        assert got2.id == got1.id
        assert got2.status == ReleaseStatus.RELEASED
        assert got2.released_at is not None


class TestFeatureFlagRepo:
    async def test_upsert_and_list(self, db):
        repo = SQLiteFeatureFlagRepository(db)
        f1 = FeatureFlag(
            id="f1", project_id="p", name="new_ux", owner="growth",
            rollout_percent=25,
        )
        got1 = await repo.upsert(f1)
        f2 = FeatureFlag(
            id="f2", project_id="p", name="new_ux", owner="growth",
            state=FlagState.ARCHIVED,
        )
        got2 = await repo.upsert(f2)
        assert got2.id == got1.id
        assert got2.state == FlagState.ARCHIVED


class TestRollbackActionRepo:
    async def test_add_update_list(self, db):
        repo = SQLiteRollbackActionRepository(db)
        a = RollbackAction(
            id="a1", project_id="p", release_version="1.0.0",
            revert_ref="abc123", status=RollbackStatus.READY,
        )
        await repo.add(a)

        got = await repo.get_by_id("a1")
        assert got is not None
        assert got.status == RollbackStatus.READY

        from dataclasses import replace
        executed = replace(
            got, status=RollbackStatus.EXECUTED,
            executed_at=datetime.now(timezone.utc),
        )
        await repo.update(executed)

        refreshed = await repo.get_by_id("a1")
        assert refreshed.status == RollbackStatus.EXECUTED
        assert refreshed.executed_at is not None

        rows = await repo.list_for_project("p")
        assert len(rows) == 1
