"""Entities for the Scheduling bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.scheduling.value_objects import CronExpression


@dataclass(frozen=True)
class Schedule:
    """A recurring cycle schedule for a project."""

    id: int = 0
    project_id: str = ""
    cron: CronExpression = field(default_factory=lambda: CronExpression("0 8 * * 1-5"))
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def disable(self) -> Schedule:
        return Schedule(
            id=self.id,
            project_id=self.project_id,
            cron=self.cron,
            enabled=False,
            last_run=self.last_run,
            next_run=None,
            created_at=self.created_at,
        )

    def enable(self) -> Schedule:
        return Schedule(
            id=self.id,
            project_id=self.project_id,
            cron=self.cron,
            enabled=True,
            last_run=self.last_run,
            next_run=self.next_run,
            created_at=self.created_at,
        )

    def mark_run(self, next_run: datetime | None = None) -> Schedule:
        return Schedule(
            id=self.id,
            project_id=self.project_id,
            cron=self.cron,
            enabled=self.enabled,
            last_run=datetime.now(timezone.utc),
            next_run=next_run,
            created_at=self.created_at,
        )
