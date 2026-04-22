"""Application service for autonomy-spectrum config (Phase L)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from theswarm.domain.autonomy_config.entities import AutonomyConfig
from theswarm.domain.autonomy_config.value_objects import AutonomyLevel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class AutonomyConfigService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def set_level(
        self, project_id: str, role: str, level: AutonomyLevel,
        note: str = "", actor: str = "",
    ) -> AutonomyConfig:
        now = _now()
        cfg = AutonomyConfig(
            id=_uid(), project_id=project_id, role=role,
            level=level, note=note, updated_by=actor, updated_at=now,
        )
        return await self._repo.upsert(cfg)

    async def get(
        self, project_id: str, role: str,
    ) -> AutonomyConfig | None:
        return await self._repo.get(project_id, role)

    async def list_for_project(
        self, project_id: str,
    ) -> list[AutonomyConfig]:
        return await self._repo.list_for_project(project_id)

    async def list_all(self) -> list[AutonomyConfig]:
        return await self._repo.list_all()
