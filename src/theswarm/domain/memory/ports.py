"""Ports for the Memory bounded context."""

from __future__ import annotations

from typing import Protocol

from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.value_objects import MemoryCategory


class MemoryStore(Protocol):
    """Persistence port for agent memory."""

    async def load(self, project_id: str = "") -> list[MemoryEntry]: ...
    async def append(self, entries: list[MemoryEntry]) -> None: ...
    async def query(
        self,
        project_id: str = "",
        category: MemoryCategory | None = None,
        agent: str = "",
        limit: int = 50,
    ) -> list[MemoryEntry]: ...
    async def count(self, project_id: str = "") -> int: ...
    async def replace_all(self, project_id: str, entries: list[MemoryEntry]) -> None: ...
