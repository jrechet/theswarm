"""Ports for the Cycles bounded context."""

from __future__ import annotations

from typing import Protocol

from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.events import DomainEvent


class CycleRepository(Protocol):
    async def get(self, cycle_id: CycleId) -> Cycle | None: ...
    async def list_by_project(self, project_id: str, limit: int = 30) -> list[Cycle]: ...
    async def save(self, cycle: Cycle) -> None: ...


class EventEmitter(Protocol):
    async def emit(self, event: DomainEvent) -> None: ...
