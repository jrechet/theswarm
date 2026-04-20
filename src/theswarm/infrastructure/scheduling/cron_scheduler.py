"""Asyncio-based cron scheduler that triggers development cycles."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from theswarm.application.commands.run_cycle import RunCycleCommand, RunCycleHandler
from theswarm.domain.projects.ports import ProjectRepository
from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.ports import ScheduleRepository
from theswarm.domain.scheduling.value_objects import TriggerType

log = logging.getLogger(__name__)


class CronScheduler:
    """Periodically checks enabled schedules and triggers cycles when due.

    Uses a simple tick-based approach: every `check_interval` seconds, it
    queries enabled schedules and compares their next_run to now. When a
    schedule is due, it triggers a cycle via RunCycleHandler and updates
    the schedule's last_run and next_run.
    """

    def __init__(
        self,
        schedule_repo: ScheduleRepository,
        cycle_handler: RunCycleHandler,
        check_interval: float = 60.0,
        project_repo: ProjectRepository | None = None,
    ) -> None:
        self._schedule_repo = schedule_repo
        self._cycle_handler = cycle_handler
        self._check_interval = check_interval
        self._project_repo = project_repo
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("CronScheduler started (interval=%.0fs)", self._check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("CronScheduler stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception:
                log.exception("Scheduler tick failed")
            await asyncio.sleep(self._check_interval)

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        schedules = await self._schedule_repo.list_enabled()

        for schedule in schedules:
            if not _is_due(schedule, now):
                continue
            if await self._is_project_paused(schedule.project_id):
                log.info(
                    "Skipping scheduled cycle for paused project=%s",
                    schedule.project_id,
                )
                continue
            await self._trigger(schedule, now)

    async def _is_project_paused(self, project_id: str) -> bool:
        if self._project_repo is None:
            return False
        try:
            project = await self._project_repo.get(project_id)
        except Exception:
            log.exception("Failed to load project %s for pause check", project_id)
            return False
        return bool(project is not None and project.config.paused)

    async def _trigger(self, schedule: Schedule, now: datetime) -> None:
        log.info("Triggering scheduled cycle for project=%s", schedule.project_id)
        try:
            cmd = RunCycleCommand(
                project_id=schedule.project_id,
                triggered_by=TriggerType.SCHEDULE.value,
            )
            cycle_id = await self._cycle_handler.handle(cmd)
            log.info("Scheduled cycle started: %s", cycle_id)

            next_run = compute_next_run(schedule, now)
            updated = schedule.mark_run(next_run=next_run)
            await self._schedule_repo.save(updated)
        except Exception:
            log.exception(
                "Failed to trigger scheduled cycle for project=%s",
                schedule.project_id,
            )

    async def tick_once(self) -> None:
        """Run a single tick (for testing)."""
        await self._tick()


def _is_due(schedule: Schedule, now: datetime) -> bool:
    """Check if a schedule should fire at the given time."""
    if schedule.next_run is not None:
        return now >= schedule.next_run
    if schedule.last_run is None:
        return _cron_matches(schedule, now)
    return False


def _cron_matches(schedule: Schedule, now: datetime) -> bool:
    """Simple cron matching: check if current minute/hour/day matches."""
    parts = schedule.cron.value.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    return (
        _field_matches(minute, now.minute)
        and _field_matches(hour, now.hour)
        and _field_matches(dom, now.day)
        and _field_matches(month, now.month)
        and _field_matches(dow, now.weekday())  # 0=Monday in Python
    )


def _field_matches(field: str, value: int) -> bool:
    """Check if a cron field matches a value."""
    if field == "*":
        return True
    for part in field.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            step_int = int(step)
            if step_int == 0:
                continue
            start = 0 if base == "*" else int(base)
            if (value - start) % step_int == 0 and value >= start:
                return True
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        else:
            if int(part) == value:
                return True
    return False


def compute_next_run(schedule: Schedule, after: datetime) -> datetime:
    """Compute the next run time by advancing minute-by-minute.

    This is a simple brute-force approach. For production, consider using
    croniter. Limits to 48h lookahead.
    """
    from datetime import timedelta

    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = after + timedelta(hours=48)

    while candidate < limit:
        if _cron_matches(schedule, candidate):
            return candidate
        candidate += timedelta(minutes=1)

    # Fallback: next day same time
    return after + timedelta(days=1)
