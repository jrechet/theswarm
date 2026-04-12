"""Commands: create, update, delete schedules."""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.projects.ports import ProjectRepository
from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.ports import ScheduleRepository
from theswarm.domain.scheduling.value_objects import CronExpression


@dataclass(frozen=True)
class SetScheduleCommand:
    project_id: str
    cron: str
    enabled: bool = True


@dataclass(frozen=True)
class DisableScheduleCommand:
    project_id: str


@dataclass(frozen=True)
class DeleteScheduleCommand:
    project_id: str


class SetScheduleHandler:
    def __init__(
        self,
        project_repo: ProjectRepository,
        schedule_repo: ScheduleRepository,
    ) -> None:
        self._project_repo = project_repo
        self._schedule_repo = schedule_repo

    async def handle(self, cmd: SetScheduleCommand) -> Schedule:
        project = await self._project_repo.get(cmd.project_id)
        if project is None:
            raise ValueError(f"Project not found: {cmd.project_id}")

        cron = CronExpression(cmd.cron)
        existing = await self._schedule_repo.get_by_project(cmd.project_id)

        if existing is not None:
            updated = Schedule(
                id=existing.id,
                project_id=cmd.project_id,
                cron=cron,
                enabled=cmd.enabled,
                last_run=existing.last_run,
                next_run=existing.next_run,
            )
            await self._schedule_repo.save(updated)
            return updated

        schedule = Schedule(project_id=cmd.project_id, cron=cron, enabled=cmd.enabled)
        await self._schedule_repo.save(schedule)
        return schedule


class DisableScheduleHandler:
    def __init__(self, schedule_repo: ScheduleRepository) -> None:
        self._schedule_repo = schedule_repo

    async def handle(self, cmd: DisableScheduleCommand) -> None:
        existing = await self._schedule_repo.get_by_project(cmd.project_id)
        if existing is None:
            raise ValueError(f"No schedule for project: {cmd.project_id}")
        await self._schedule_repo.save(existing.disable())


class DeleteScheduleHandler:
    def __init__(self, schedule_repo: ScheduleRepository) -> None:
        self._schedule_repo = schedule_repo

    async def handle(self, cmd: DeleteScheduleCommand) -> None:
        existing = await self._schedule_repo.get_by_project(cmd.project_id)
        if existing is None:
            raise ValueError(f"No schedule for project: {cmd.project_id}")
        await self._schedule_repo.delete(existing.id)
