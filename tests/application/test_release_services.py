"""Phase J application tests — Release services."""

from __future__ import annotations

import pytest

from theswarm.application.services.release import (
    FeatureFlagService,
    ReleaseVersionService,
    RollbackActionService,
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
    conn = await init_db(str(tmp_path / "release_svc.db"))
    yield conn
    await conn.close()


class TestReleaseVersionService:
    async def test_draft_then_release_then_rollback(self, db):
        svc = ReleaseVersionService(SQLiteReleaseVersionRepository(db))
        draft = await svc.draft("p", "1.0.0", summary="first")
        assert draft.status == ReleaseStatus.DRAFT

        released = await svc.mark_released("p", "1.0.0")
        assert released.status == ReleaseStatus.RELEASED
        assert released.is_live
        assert released.released_at is not None

        rolled = await svc.mark_rolled_back("p", "1.0.0")
        assert rolled.status == ReleaseStatus.ROLLED_BACK

    async def test_draft_idempotent(self, db):
        svc = ReleaseVersionService(SQLiteReleaseVersionRepository(db))
        a = await svc.draft("p", "1.0.0")
        b = await svc.draft("p", "1.0.0")
        assert a.id == b.id

    async def test_mark_missing_raises(self, db):
        svc = ReleaseVersionService(SQLiteReleaseVersionRepository(db))
        with pytest.raises(ValueError):
            await svc.mark_released("p", "99.0.0")


class TestFeatureFlagService:
    async def test_upsert_clamps_rollout(self, db):
        svc = FeatureFlagService(SQLiteFeatureFlagRepository(db))
        f = await svc.upsert(
            "p", "new_ux", owner="growth", rollout_percent=150,
        )
        assert f.rollout_percent == 100

        f2 = await svc.upsert(
            "p", "new_ux", owner="growth", rollout_percent=-10,
        )
        assert f2.rollout_percent == 0

    async def test_archive(self, db):
        svc = FeatureFlagService(SQLiteFeatureFlagRepository(db))
        await svc.upsert("p", "new_ux")
        archived = await svc.archive("p", "new_ux")
        assert archived.state == FlagState.ARCHIVED

    async def test_archive_missing_raises(self, db):
        svc = FeatureFlagService(SQLiteFeatureFlagRepository(db))
        with pytest.raises(ValueError):
            await svc.archive("p", "nope")


class TestRollbackActionService:
    async def test_arm_execute_flow(self, db):
        svc = RollbackActionService(SQLiteRollbackActionRepository(db))
        a = await svc.arm("p", "1.0.0", revert_ref="abc123", note="context")
        assert a.is_armed

        executed = await svc.execute(a.id)
        assert executed.status == RollbackStatus.EXECUTED
        assert executed.executed_at is not None

    async def test_mark_obsolete(self, db):
        svc = RollbackActionService(SQLiteRollbackActionRepository(db))
        a = await svc.arm("p", "1.0.0", revert_ref="abc123")
        obsolete = await svc.mark_obsolete(a.id)
        assert obsolete.status == RollbackStatus.OBSOLETE

    async def test_execute_missing_raises(self, db):
        svc = RollbackActionService(SQLiteRollbackActionRepository(db))
        with pytest.raises(ValueError):
            await svc.execute("missing")
