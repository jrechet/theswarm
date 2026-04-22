"""Application service for semantic memory (Phase L)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.semantic_memory.entities import SemanticMemoryEntry


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _clean_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for t in tags:
        t = t.strip().casefold()
        if t and t not in seen:
            seen[t] = None
    return tuple(seen.keys())


class SemanticMemoryService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, title: str, content: str = "",
        project_id: str = "",
        tags: tuple[str, ...] = (),
        enabled: bool = True,
        source: str = "",
    ) -> SemanticMemoryEntry:
        now = _now()
        e = SemanticMemoryEntry(
            id=_uid(), project_id=project_id,
            title=title, content=content, tags=_clean_tags(tags),
            enabled=enabled, source=source,
            created_at=now, updated_at=now,
        )
        return await self._repo.add(e)

    async def set_enabled(
        self, entry_id: str, enabled: bool,
    ) -> SemanticMemoryEntry:
        existing = await self._repo.get_by_id(entry_id)
        if existing is None:
            raise ValueError(f"Memory entry not found: {entry_id}")
        updated = replace(existing, enabled=enabled, updated_at=_now())
        return await self._repo.update(updated)

    async def list(
        self, project_id: str | None = None,
    ) -> list[SemanticMemoryEntry]:
        return await self._repo.list_all(project_id=project_id)

    async def search(
        self, query: str = "", tag: str = "",
        project_id: str | None = None,
    ) -> list[SemanticMemoryEntry]:
        """Return only enabled entries that match query/tag filter."""
        tag = tag.strip().casefold()
        entries = await self._repo.list_all(project_id=project_id)
        return [e for e in entries if e.matches(query, tag)]
