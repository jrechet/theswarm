"""Entities for the Release bounded context (Phase J)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from theswarm.domain.release.value_objects import (
    FlagState,
    ReleaseStatus,
    RollbackStatus,
)


@dataclass(frozen=True)
class ReleaseVersion:
    """A cut release per project (semver-friendly string)."""

    id: str
    project_id: str
    version: str  # e.g. "1.2.0"
    status: ReleaseStatus = ReleaseStatus.DRAFT
    summary: str = ""
    released_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_live(self) -> bool:
        return self.status == ReleaseStatus.RELEASED


@dataclass(frozen=True)
class FeatureFlag:
    """A feature flag tracked for ownership and cleanup."""

    id: str
    project_id: str
    name: str
    owner: str = ""
    description: str = ""
    state: FlagState = FlagState.ACTIVE
    rollout_percent: int = 0  # 0..100
    cleanup_after_days: int = 90
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_cleanup_overdue(self) -> bool:
        if self.state == FlagState.ARCHIVED:
            return False
        age = datetime.now(timezone.utc) - self.created_at
        return age > timedelta(days=self.cleanup_after_days)


@dataclass(frozen=True)
class RollbackAction:
    """A one-click revert action attached to a release."""

    id: str
    project_id: str
    release_version: str
    revert_ref: str = ""  # git ref or PR URL to revert to
    status: RollbackStatus = RollbackStatus.READY
    note: str = ""
    executed_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_armed(self) -> bool:
        return self.status == RollbackStatus.READY and bool(self.revert_ref)
