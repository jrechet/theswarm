"""Sprint F M3 — nightly memory compaction.

Keeps each project's ``memory_entries`` footprint bounded by (a) deduping
identical entries, then (b) trimming the oldest surplus once either a
byte budget or an entry-count budget is exceeded.

Runs as an asyncio loop registered at server boot — not through the
per-project ``Schedule`` system, which is dedicated to cycle triggers.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope

log = logging.getLogger(__name__)


# 1 MB cap per project is the Sprint F M3 AC.
_DEFAULT_MAX_BYTES = 1_000_000
_DEFAULT_MAX_ENTRIES = 2_000


class _StoreLike(Protocol):
    async def load(self, project_id: str = "") -> list[MemoryEntry]: ...
    async def replace_all(
        self, project_id: str, entries: list[MemoryEntry],
    ) -> None: ...


class _ProjectRepoLike(Protocol):
    async def list_all(self) -> list: ...


@dataclass(frozen=True)
class CompactionResult:
    project_id: str
    before: int
    after: int
    deduped: int
    trimmed: int

    @property
    def removed(self) -> int:
        return self.before - self.after


def _entry_bytes(entry: MemoryEntry) -> int:
    # Rough byte accounting used only for budgeting — not for storage sizing.
    return len(entry.content.encode("utf-8")) + len(entry.agent) + 32


def _dedup(entries: list[MemoryEntry]) -> tuple[list[MemoryEntry], int]:
    """Collapse exact duplicates, keeping the earliest by ``created_at``."""
    seen: dict[tuple[str, str, str], MemoryEntry] = {}
    for e in entries:
        key = (e.category.value, e.agent, e.content)
        existing = seen.get(key)
        if existing is None or e.created_at < existing.created_at:
            seen[key] = e
    kept = sorted(seen.values(), key=lambda e: e.created_at)
    removed = len(entries) - len(kept)
    return kept, removed


def _trim_to_budget(
    entries: list[MemoryEntry],
    max_bytes: int,
    max_entries: int,
    project_id: str,
    now: datetime,
) -> tuple[list[MemoryEntry], int]:
    """Drop oldest entries until both caps hold; emit a compaction marker."""
    total = sum(_entry_bytes(e) for e in entries)
    if total <= max_bytes and len(entries) <= max_entries:
        return entries, 0

    ordered = sorted(entries, key=lambda e: e.created_at)
    trimmed_count = 0
    while ordered and (
        sum(_entry_bytes(e) for e in ordered) > max_bytes
        or len(ordered) > max_entries
    ):
        ordered.pop(0)
        trimmed_count += 1

    if trimmed_count > 0:
        marker = MemoryEntry(
            category=MemoryCategory.CONVENTIONS,
            content=f"[compaction] pruned {trimmed_count} oldest memory entries on {now.date().isoformat()}",
            agent="memory-compactor",
            scope=ProjectScope(project_id=project_id),
            cycle_date=now.date().isoformat(),
            created_at=now,
        )
        ordered.insert(0, marker)
    return ordered, trimmed_count


class MemoryCompactionService:
    """Dedup + size-bound a project's memory entries."""

    def __init__(
        self,
        memory_store: _StoreLike,
        project_repo: _ProjectRepoLike | None = None,
        *,
        max_bytes_per_project: int = _DEFAULT_MAX_BYTES,
        max_entries_per_project: int = _DEFAULT_MAX_ENTRIES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = memory_store
        self._project_repo = project_repo
        self._max_bytes = max_bytes_per_project
        self._max_entries = max_entries_per_project
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def compact(self, project_id: str) -> CompactionResult:
        current = await self._store.load(project_id)
        project_scoped = [e for e in current if e.scope.project_id == project_id]
        before = len(project_scoped)

        deduped, dup_removed = _dedup(project_scoped)
        trimmed, trim_removed = _trim_to_budget(
            deduped, self._max_bytes, self._max_entries,
            project_id, self._clock(),
        )

        if dup_removed or trim_removed:
            await self._store.replace_all(project_id, trimmed)

        return CompactionResult(
            project_id=project_id,
            before=before,
            after=len(trimmed),
            deduped=dup_removed,
            trimmed=trim_removed,
        )

    async def run_all(self, project_ids: Iterable[str] | None = None) -> list[CompactionResult]:
        if project_ids is None:
            if self._project_repo is None:
                return []
            projects = await self._project_repo.list_all()
            project_ids = [p.id for p in projects]

        results: list[CompactionResult] = []
        for pid in project_ids:
            try:
                results.append(await self.compact(pid))
            except Exception:
                log.exception("Memory compaction failed for project %s", pid)
        return results


async def run_compaction_loop(
    service: MemoryCompactionService,
    *,
    interval_seconds: float = 86_400.0,
    initial_delay_seconds: float = 60.0,
) -> None:
    """Background task — sleeps, then compacts, forever.

    Designed to be cancelled at shutdown; exceptions per iteration are
    swallowed and logged so one bad project can't kill the loop.
    """
    try:
        await asyncio.sleep(initial_delay_seconds)
        while True:
            try:
                results = await service.run_all()
                log.info(
                    "Memory compaction done: %d projects, %d entries removed",
                    len(results), sum(r.removed for r in results),
                )
            except Exception:
                log.exception("Memory compaction cycle failed")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("Memory compaction loop cancelled")
        raise
