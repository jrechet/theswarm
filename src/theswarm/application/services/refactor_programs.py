"""Application service for refactor programs (Phase L)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.refactor_programs.entities import RefactorProgram
from theswarm.domain.refactor_programs.value_objects import (
    RefactorProgramStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _dedupe_projects(projects: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for p in projects:
        p = p.strip()
        if p and p not in seen:
            seen[p] = None
    return tuple(seen.keys())


class RefactorProgramService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, title: str, rationale: str = "",
        target_projects: tuple[str, ...] = (),
        owner: str = "",
        status: RefactorProgramStatus = RefactorProgramStatus.PROPOSED,
    ) -> RefactorProgram:
        existing = await self._repo.get_by_title(title)
        now = _now()
        projects = _dedupe_projects(target_projects)
        if existing is None:
            p = RefactorProgram(
                id=_uid(), title=title, rationale=rationale,
                status=status, target_projects=projects,
                owner=owner, created_at=now, updated_at=now,
            )
        else:
            p = replace(
                existing, rationale=rationale,
                status=status, target_projects=projects,
                owner=owner, updated_at=now,
            )
        return await self._repo.upsert(p)

    async def activate(self, title: str) -> RefactorProgram:
        existing = await self._repo.get_by_title(title)
        if existing is None:
            raise ValueError(f"Refactor program not found: {title}")
        now = _now()
        updated = replace(
            existing, status=RefactorProgramStatus.ACTIVE,
            started_at=existing.started_at or now, updated_at=now,
        )
        return await self._repo.upsert(updated)

    async def complete(self, title: str) -> RefactorProgram:
        existing = await self._repo.get_by_title(title)
        if existing is None:
            raise ValueError(f"Refactor program not found: {title}")
        now = _now()
        updated = replace(
            existing, status=RefactorProgramStatus.COMPLETED,
            completed_at=now, updated_at=now,
        )
        return await self._repo.upsert(updated)

    async def cancel(self, title: str) -> RefactorProgram:
        existing = await self._repo.get_by_title(title)
        if existing is None:
            raise ValueError(f"Refactor program not found: {title}")
        now = _now()
        updated = replace(
            existing, status=RefactorProgramStatus.CANCELLED,
            completed_at=now, updated_at=now,
        )
        return await self._repo.upsert(updated)

    async def add_project(
        self, title: str, project_id: str,
    ) -> RefactorProgram:
        existing = await self._repo.get_by_title(title)
        if existing is None:
            raise ValueError(f"Refactor program not found: {title}")
        if project_id in existing.target_projects:
            return existing
        projects = _dedupe_projects(
            existing.target_projects + (project_id,),
        )
        updated = replace(
            existing, target_projects=projects, updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def remove_project(
        self, title: str, project_id: str,
    ) -> RefactorProgram:
        existing = await self._repo.get_by_title(title)
        if existing is None:
            raise ValueError(f"Refactor program not found: {title}")
        projects = tuple(
            p for p in existing.target_projects if p != project_id
        )
        updated = replace(
            existing, target_projects=projects, updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def list(self) -> list[RefactorProgram]:
        return await self._repo.list_all()
