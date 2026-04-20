"""Tests for CronScheduler."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.value_objects import CronExpression
from theswarm.infrastructure.scheduling.cron_scheduler import (
    CronScheduler,
    _cron_matches,
    _field_matches,
    _is_due,
    compute_next_run,
)


# ── _field_matches ────────────────────────────────────────────────


class TestFieldMatches:
    def test_wildcard(self):
        assert _field_matches("*", 5)

    def test_exact(self):
        assert _field_matches("5", 5)
        assert not _field_matches("5", 6)

    def test_range(self):
        assert _field_matches("1-5", 3)
        assert not _field_matches("1-5", 6)

    def test_step(self):
        assert _field_matches("*/15", 0)
        assert _field_matches("*/15", 15)
        assert _field_matches("*/15", 30)
        assert not _field_matches("*/15", 7)

    def test_step_with_base(self):
        assert _field_matches("5/10", 5)
        assert _field_matches("5/10", 15)
        assert not _field_matches("5/10", 6)

    def test_list(self):
        assert _field_matches("1,3,5", 3)
        assert not _field_matches("1,3,5", 4)

    def test_zero_step(self):
        assert not _field_matches("*/0", 5)


# ── _cron_matches ─────────────────────────────────────────────────


class TestCronMatches:
    def test_every_minute(self):
        sched = Schedule(cron=CronExpression("* * * * *"))
        now = datetime(2026, 4, 12, 10, 30, tzinfo=timezone.utc)
        assert _cron_matches(sched, now)

    def test_specific_time(self):
        sched = Schedule(cron=CronExpression("0 8 * * *"))
        at_8 = datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc)
        at_9 = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
        assert _cron_matches(sched, at_8)
        assert not _cron_matches(sched, at_9)

    def test_weekdays_only(self):
        # Monday=0 in Python. April 13, 2026 is a Monday
        sched = Schedule(cron=CronExpression("0 8 * * 0-4"))
        monday = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)
        # April 18, 2026 is a Saturday (weekday=5)
        saturday = datetime(2026, 4, 18, 8, 0, tzinfo=timezone.utc)
        assert _cron_matches(sched, monday)
        assert not _cron_matches(sched, saturday)


# ── _is_due ───────────────────────────────────────────────────────


class TestIsDue:
    def test_due_when_next_run_passed(self):
        sched = Schedule(
            cron=CronExpression("0 8 * * *"),
            next_run=datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc),
        )
        now = datetime(2026, 4, 12, 8, 1, tzinfo=timezone.utc)
        assert _is_due(sched, now)

    def test_not_due_when_next_run_in_future(self):
        sched = Schedule(
            cron=CronExpression("0 8 * * *"),
            next_run=datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc),
        )
        now = datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc)
        assert not _is_due(sched, now)

    def test_due_when_no_next_run_and_never_ran(self):
        sched = Schedule(cron=CronExpression("0 8 * * *"))
        now = datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc)
        assert _is_due(sched, now)

    def test_not_due_when_no_next_run_but_already_ran(self):
        sched = Schedule(
            cron=CronExpression("0 8 * * *"),
            last_run=datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc),
        )
        now = datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
        assert not _is_due(sched, now)


# ── compute_next_run ──────────────────────────────────────────────


class TestComputeNextRun:
    def test_daily_at_8(self):
        sched = Schedule(cron=CronExpression("0 8 * * *"))
        after = datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc)
        nxt = compute_next_run(sched, after)
        assert nxt.hour == 8
        assert nxt.minute == 0
        assert nxt.day == 13

    def test_every_hour(self):
        sched = Schedule(cron=CronExpression("0 * * * *"))
        after = datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc)
        nxt = compute_next_run(sched, after)
        assert nxt == datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)


# ── CronScheduler ────────────────────────────────────────────────


class TestCronScheduler:
    async def test_start_stop(self):
        repo = AsyncMock()
        handler = AsyncMock()
        scheduler = CronScheduler(repo, handler, check_interval=0.01)

        await scheduler.start()
        assert scheduler.running
        await scheduler.stop()
        assert not scheduler.running

    async def test_tick_triggers_due_schedule(self):
        schedule = Schedule(
            id=1,
            project_id="proj-1",
            cron=CronExpression("* * * * *"),
            next_run=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        repo = AsyncMock()
        repo.list_enabled.return_value = [schedule]
        handler = AsyncMock()
        handler.handle.return_value = "cycle-123"

        scheduler = CronScheduler(repo, handler)
        await scheduler.tick_once()

        handler.handle.assert_called_once()
        repo.save.assert_called_once()

    async def test_tick_skips_not_due_schedule(self):
        schedule = Schedule(
            id=1,
            project_id="proj-1",
            cron=CronExpression("0 8 * * *"),
            next_run=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        repo = AsyncMock()
        repo.list_enabled.return_value = [schedule]
        handler = AsyncMock()

        scheduler = CronScheduler(repo, handler)
        await scheduler.tick_once()

        handler.handle.assert_not_called()

    async def test_tick_handles_handler_error(self):
        schedule = Schedule(
            id=1,
            project_id="proj-1",
            cron=CronExpression("* * * * *"),
            next_run=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        repo = AsyncMock()
        repo.list_enabled.return_value = [schedule]
        handler = AsyncMock()
        handler.handle.side_effect = ValueError("Project not found")

        scheduler = CronScheduler(repo, handler)
        # Should not raise
        await scheduler.tick_once()

    async def test_start_is_idempotent(self):
        repo = AsyncMock()
        handler = AsyncMock()
        scheduler = CronScheduler(repo, handler, check_interval=60)

        await scheduler.start()
        await scheduler.start()  # No-op
        assert scheduler.running
        await scheduler.stop()

    async def test_paused_project_skipped(self):
        from theswarm.domain.projects.entities import Project, ProjectConfig
        from theswarm.domain.projects.value_objects import RepoUrl

        schedule = Schedule(
            id=1,
            project_id="proj-paused",
            cron=CronExpression("* * * * *"),
            next_run=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        repo = AsyncMock()
        repo.list_enabled.return_value = [schedule]
        handler = AsyncMock()

        project_repo = AsyncMock()
        project_repo.get.return_value = Project(
            id="proj-paused",
            repo=RepoUrl("o/r"),
            config=ProjectConfig(paused=True),
        )

        scheduler = CronScheduler(repo, handler, project_repo=project_repo)
        await scheduler.tick_once()

        handler.handle.assert_not_called()
        repo.save.assert_not_called()

    async def test_unpaused_project_triggers(self):
        from theswarm.domain.projects.entities import Project, ProjectConfig
        from theswarm.domain.projects.value_objects import RepoUrl

        schedule = Schedule(
            id=1,
            project_id="proj-ok",
            cron=CronExpression("* * * * *"),
            next_run=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        repo = AsyncMock()
        repo.list_enabled.return_value = [schedule]
        handler = AsyncMock()
        handler.handle.return_value = "cycle-xyz"

        project_repo = AsyncMock()
        project_repo.get.return_value = Project(
            id="proj-ok",
            repo=RepoUrl("o/r"),
            config=ProjectConfig(paused=False),
        )

        scheduler = CronScheduler(repo, handler, project_repo=project_repo)
        await scheduler.tick_once()

        handler.handle.assert_called_once()
