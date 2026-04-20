"""Sprint E M1 — query for the per-project memory viewer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.ports import MemoryStore
from theswarm.domain.memory.value_objects import MemoryCategory


@dataclass(frozen=True)
class MemoryEntryView:
    category: str
    content: str
    agent: str
    project_id: str
    cycle_date: str
    created_at: datetime

    @property
    def is_global(self) -> bool:
        return not self.project_id


class ListProjectMemoryQuery:
    """Read project + global memory entries for the viewer."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self._store = memory_store

    async def execute(
        self,
        project_id: str,
        category: str = "",
        agent: str = "",
        limit: int = 500,
    ) -> list[MemoryEntryView]:
        cat: MemoryCategory | None = None
        if category:
            try:
                cat = MemoryCategory(category)
            except ValueError:
                cat = None
        entries = await self._store.query(
            project_id=project_id, category=cat, agent=agent, limit=limit,
        )
        return [self._to_view(e) for e in entries]

    @staticmethod
    def _to_view(entry: MemoryEntry) -> MemoryEntryView:
        return MemoryEntryView(
            category=entry.category.value,
            content=entry.content,
            agent=entry.agent,
            project_id=entry.scope.project_id,
            cycle_date=entry.cycle_date,
            created_at=entry.created_at,
        )
