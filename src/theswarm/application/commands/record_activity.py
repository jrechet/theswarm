"""Command: record agent activity during a cycle."""

from __future__ import annotations

from dataclasses import dataclass, field

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.events import AgentActivity
from theswarm.domain.cycles.value_objects import CycleId


@dataclass(frozen=True)
class RecordActivityCommand:
    cycle_id: str
    project_id: str
    agent: str
    action: str
    detail: str = ""
    metadata: dict = field(default_factory=dict)


class RecordActivityHandler:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, cmd: RecordActivityCommand) -> None:
        await self._event_bus.publish(
            AgentActivity(
                cycle_id=CycleId(cmd.cycle_id),
                project_id=cmd.project_id,
                agent=cmd.agent,
                action=cmd.action,
                detail=cmd.detail,
                metadata=cmd.metadata,
            )
        )
