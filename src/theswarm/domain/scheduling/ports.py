"""Ports for the Scheduling bounded context."""

from __future__ import annotations

from typing import Protocol

from theswarm.domain.scheduling.entities import Schedule


class ScheduleRepository(Protocol):
    async def get_by_project(self, project_id: str) -> Schedule | None: ...
    async def list_enabled(self) -> list[Schedule]: ...
    async def save(self, schedule: Schedule) -> None: ...
    async def delete(self, schedule_id: int) -> None: ...
