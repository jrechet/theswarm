"""Tests for domain/scheduling — 100% coverage target."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.value_objects import CronExpression, TriggerType


class TestCronExpression:
    def test_valid(self):
        c = CronExpression("0 8 * * 1-5")
        assert str(c) == "0 8 * * 1-5"

    def test_valid_every_minute(self):
        c = CronExpression("* * * * *")
        assert str(c) == "* * * * *"

    def test_valid_complex(self):
        c = CronExpression("0,30 9-17 * * 1-5")
        assert c.value == "0,30 9-17 * * 1-5"

    def test_invalid_empty(self):
        with pytest.raises(ValueError, match="Invalid cron"):
            CronExpression("")

    def test_invalid_too_few_fields(self):
        with pytest.raises(ValueError, match="Invalid cron"):
            CronExpression("0 8 *")

    def test_invalid_letters(self):
        with pytest.raises(ValueError, match="Invalid cron"):
            CronExpression("abc def ghi jkl mno")

    def test_frozen(self):
        c = CronExpression("0 8 * * *")
        with pytest.raises(AttributeError):
            c.value = "0 9 * * *"  # type: ignore[misc]


class TestTriggerType:
    def test_values(self):
        assert TriggerType.MANUAL == "manual"
        assert TriggerType.SCHEDULE == "schedule"
        assert TriggerType.WEBHOOK == "webhook"


class TestSchedule:
    def test_creation(self):
        s = Schedule(project_id="my-app", cron=CronExpression("0 8 * * 1-5"))
        assert s.enabled is True
        assert s.last_run is None
        assert s.next_run is None

    def test_disable(self):
        s = Schedule(project_id="my-app", cron=CronExpression("0 8 * * *"))
        s2 = s.disable()
        assert s2.enabled is False
        assert s2.next_run is None
        assert s.enabled is True  # immutable

    def test_enable(self):
        s = Schedule(project_id="my-app", cron=CronExpression("0 8 * * *"), enabled=False)
        s2 = s.enable()
        assert s2.enabled is True

    def test_mark_run(self):
        s = Schedule(project_id="my-app", cron=CronExpression("0 8 * * *"))
        next_run = datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc)
        s2 = s.mark_run(next_run=next_run)
        assert s2.last_run is not None
        assert s2.next_run == next_run
        assert s.last_run is None  # immutable
