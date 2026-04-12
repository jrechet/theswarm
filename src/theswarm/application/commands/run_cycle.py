"""Command: trigger a development cycle for a project."""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import CycleFailed, CycleStarted
from theswarm.domain.cycles.ports import CycleRepository
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.projects.ports import ProjectRepository


@dataclass(frozen=True)
class RunCycleCommand:
    project_id: str
    triggered_by: str = "manual"


class RunCycleHandler:
    def __init__(
        self,
        project_repo: ProjectRepository,
        cycle_repo: CycleRepository,
        event_bus: EventBus,
    ) -> None:
        self._project_repo = project_repo
        self._cycle_repo = cycle_repo
        self._event_bus = event_bus

    async def handle(self, cmd: RunCycleCommand) -> CycleId:
        project = await self._project_repo.get(cmd.project_id)
        if project is None:
            raise ValueError(f"Project not found: {cmd.project_id}")

        cycle_id = CycleId.generate()
        cycle = Cycle(id=cycle_id, project_id=cmd.project_id)
        cycle = cycle.start(triggered_by=cmd.triggered_by)
        await self._cycle_repo.save(cycle)

        await self._event_bus.publish(
            CycleStarted(
                cycle_id=cycle_id,
                project_id=cmd.project_id,
                triggered_by=cmd.triggered_by,
            )
        )

        return cycle_id
