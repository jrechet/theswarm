"""Phase J domain tests — Release entities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


class TestReleaseVersion:
    def test_released_is_live(self):
        v = ReleaseVersion(
            id="r1", project_id="p", version="1.0.0",
            status=ReleaseStatus.RELEASED,
        )
        assert v.is_live

    def test_draft_not_live(self):
        v = ReleaseVersion(
            id="r1", project_id="p", version="1.0.0",
            status=ReleaseStatus.DRAFT,
        )
        assert not v.is_live


class TestFeatureFlag:
    def test_old_active_flag_is_cleanup_overdue(self):
        old_created = datetime.now(timezone.utc) - timedelta(days=120)
        f = FeatureFlag(
            id="f1", project_id="p", name="new_ux",
            state=FlagState.ACTIVE, cleanup_after_days=90,
            created_at=old_created,
        )
        assert f.is_cleanup_overdue

    def test_archived_never_overdue(self):
        old_created = datetime.now(timezone.utc) - timedelta(days=500)
        f = FeatureFlag(
            id="f1", project_id="p", name="new_ux",
            state=FlagState.ARCHIVED, cleanup_after_days=90,
            created_at=old_created,
        )
        assert not f.is_cleanup_overdue

    def test_fresh_not_overdue(self):
        f = FeatureFlag(
            id="f1", project_id="p", name="new_ux",
            state=FlagState.ACTIVE, cleanup_after_days=90,
        )
        assert not f.is_cleanup_overdue


class TestRollbackAction:
    def test_ready_with_ref_is_armed(self):
        a = RollbackAction(
            id="a1", project_id="p", release_version="1.0.0",
            revert_ref="abc123",
            status=RollbackStatus.READY,
        )
        assert a.is_armed

    def test_executed_not_armed(self):
        a = RollbackAction(
            id="a1", project_id="p", release_version="1.0.0",
            revert_ref="abc123",
            status=RollbackStatus.EXECUTED,
        )
        assert not a.is_armed

    def test_ready_without_ref_not_armed(self):
        a = RollbackAction(
            id="a1", project_id="p", release_version="1.0.0",
            revert_ref="", status=RollbackStatus.READY,
        )
        assert not a.is_armed
