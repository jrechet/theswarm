"""Query: get schedule for a project."""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.scheduling.ports import ScheduleRepository


@dataclass(frozen=True)
class ScheduleDTO:
    project_id: str
    cron: str
    enabled: bool
    last_run: str | None
    next_run: str | None


class GetScheduleQuery:
    def __init__(self, schedule_repo: ScheduleRepository) -> None:
        self._schedule_repo = schedule_repo

    async def execute(self, project_id: str) -> ScheduleDTO | None:
        s = await self._schedule_repo.get_by_project(project_id)
        if s is None:
            return None
        return ScheduleDTO(
            project_id=s.project_id,
            cron=str(s.cron),
            enabled=s.enabled,
            last_run=s.last_run.isoformat() if s.last_run else None,
            next_run=s.next_run.isoformat() if s.next_run else None,
        )


class ListEnabledSchedulesQuery:
    def __init__(self, schedule_repo: ScheduleRepository) -> None:
        self._schedule_repo = schedule_repo

    async def execute(self) -> list[ScheduleDTO]:
        schedules = await self._schedule_repo.list_enabled()
        return [
            ScheduleDTO(
                project_id=s.project_id,
                cron=str(s.cron),
                enabled=s.enabled,
                last_run=s.last_run.isoformat() if s.last_run else None,
                next_run=s.next_run.isoformat() if s.next_run else None,
            )
            for s in schedules
        ]
