"""Application services for the Writer bounded context (Phase J)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.writer.entities import (
    ChangelogEntry,
    DocArtifact,
    QuickstartCheck,
)
from theswarm.domain.writer.value_objects import (
    ChangeKind,
    DocKind,
    DocStatus,
    QuickstartOutcome,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class DocArtifactService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str, path: str, kind: DocKind,
        title: str = "", summary: str = "",
        status: DocStatus = DocStatus.DRAFT,
    ) -> DocArtifact:
        existing = await self._repo.get_for_path(project_id, path)
        now = _now()
        if existing is None:
            d = DocArtifact(
                id=_uid(), project_id=project_id, kind=kind, path=path,
                title=title, summary=summary, status=status,
                last_reviewed_at=None,
                created_at=now, updated_at=now,
            )
        else:
            d = replace(
                existing, kind=kind, title=title, summary=summary,
                status=status, updated_at=now,
            )
        return await self._repo.upsert(d)

    async def mark_status(
        self, project_id: str, path: str, status: DocStatus,
    ) -> DocArtifact:
        existing = await self._repo.get_for_path(project_id, path)
        if existing is None:
            raise ValueError(f"Doc not found: {project_id}/{path}")
        now = _now()
        last_reviewed = (
            now if status == DocStatus.READY else existing.last_reviewed_at
        )
        updated = replace(
            existing, status=status, last_reviewed_at=last_reviewed,
            updated_at=now,
        )
        return await self._repo.upsert(updated)

    async def list(self, project_id: str) -> list[DocArtifact]:
        return await self._repo.list_for_project(project_id)


class QuickstartCheckService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, project_id: str, step_count: int = 0,
        duration_seconds: float = 0.0,
        outcome: QuickstartOutcome = QuickstartOutcome.SKIPPED,
        failure_step: str = "", note: str = "",
    ) -> QuickstartCheck:
        q = QuickstartCheck(
            id=_uid(), project_id=project_id, step_count=step_count,
            duration_seconds=duration_seconds, outcome=outcome,
            failure_step=failure_step, note=note, created_at=_now(),
        )
        return await self._repo.add(q)

    async def list(self, project_id: str) -> list[QuickstartCheck]:
        return await self._repo.list_for_project(project_id)


class ChangelogService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, project_id: str, kind: ChangeKind, summary: str,
        pr_url: str = "", version: str = "",
    ) -> ChangelogEntry:
        c = ChangelogEntry(
            id=_uid(), project_id=project_id, kind=kind, summary=summary,
            pr_url=pr_url, version=version, created_at=_now(),
        )
        return await self._repo.add(c)

    async def list(self, project_id: str) -> list[ChangelogEntry]:
        return await self._repo.list_for_project(project_id)

    async def list_for_version(
        self, project_id: str, version: str,
    ) -> list[ChangelogEntry]:
        return await self._repo.list_for_version(project_id, version)

    async def list_unreleased(
        self, project_id: str,
    ) -> list[ChangelogEntry]:
        return await self._repo.list_unreleased(project_id)
