"""Application services for the Release bounded context (Phase J)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class ReleaseVersionService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def draft(
        self, project_id: str, version: str, summary: str = "",
    ) -> ReleaseVersion:
        existing = await self._repo.get_for_version(project_id, version)
        if existing is not None:
            return existing
        now = _now()
        r = ReleaseVersion(
            id=_uid(), project_id=project_id, version=version,
            status=ReleaseStatus.DRAFT, summary=summary,
            created_at=now, updated_at=now,
        )
        return await self._repo.upsert(r)

    async def mark_released(
        self, project_id: str, version: str,
    ) -> ReleaseVersion:
        existing = await self._repo.get_for_version(project_id, version)
        if existing is None:
            raise ValueError(f"Release not found: {project_id}/{version}")
        now = _now()
        updated = replace(
            existing, status=ReleaseStatus.RELEASED,
            released_at=now, updated_at=now,
        )
        return await self._repo.upsert(updated)

    async def mark_rolled_back(
        self, project_id: str, version: str,
    ) -> ReleaseVersion:
        existing = await self._repo.get_for_version(project_id, version)
        if existing is None:
            raise ValueError(f"Release not found: {project_id}/{version}")
        updated = replace(
            existing, status=ReleaseStatus.ROLLED_BACK, updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def list(self, project_id: str) -> list[ReleaseVersion]:
        return await self._repo.list_for_project(project_id)


class FeatureFlagService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str, name: str, owner: str = "",
        description: str = "",
        state: FlagState = FlagState.ACTIVE,
        rollout_percent: int = 0, cleanup_after_days: int = 90,
    ) -> FeatureFlag:
        rollout = max(0, min(100, rollout_percent))
        existing = await self._repo.get_for_name(project_id, name)
        now = _now()
        if existing is None:
            f = FeatureFlag(
                id=_uid(), project_id=project_id, name=name, owner=owner,
                description=description, state=state,
                rollout_percent=rollout,
                cleanup_after_days=cleanup_after_days,
                created_at=now, updated_at=now,
            )
        else:
            f = replace(
                existing, owner=owner, description=description,
                state=state, rollout_percent=rollout,
                cleanup_after_days=cleanup_after_days,
                updated_at=now,
            )
        return await self._repo.upsert(f)

    async def archive(self, project_id: str, name: str) -> FeatureFlag:
        existing = await self._repo.get_for_name(project_id, name)
        if existing is None:
            raise ValueError(f"Flag not found: {project_id}/{name}")
        updated = replace(
            existing, state=FlagState.ARCHIVED, updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def list(self, project_id: str) -> list[FeatureFlag]:
        return await self._repo.list_for_project(project_id)


class RollbackActionService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def arm(
        self, project_id: str, release_version: str,
        revert_ref: str, note: str = "",
    ) -> RollbackAction:
        a = RollbackAction(
            id=_uid(), project_id=project_id,
            release_version=release_version, revert_ref=revert_ref,
            status=RollbackStatus.READY, note=note, created_at=_now(),
        )
        return await self._repo.add(a)

    async def execute(self, action_id: str) -> RollbackAction:
        existing = await self._repo.get_by_id(action_id)
        if existing is None:
            raise ValueError(f"Rollback action not found: {action_id}")
        updated = replace(
            existing, status=RollbackStatus.EXECUTED, executed_at=_now(),
        )
        return await self._repo.update(updated)

    async def mark_obsolete(self, action_id: str) -> RollbackAction:
        existing = await self._repo.get_by_id(action_id)
        if existing is None:
            raise ValueError(f"Rollback action not found: {action_id}")
        updated = replace(existing, status=RollbackStatus.OBSOLETE)
        return await self._repo.update(updated)

    async def list(self, project_id: str) -> list[RollbackAction]:
        return await self._repo.list_for_project(project_id)
