"""Tests for Sprint B C4 — BudgetGuard."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from theswarm.application.services.budget_guard import BudgetGuard, CycleBlocked
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.value_objects import RepoUrl


_NOW = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)


class _FakeCycleRepo:
    def __init__(self, cycles: list[Cycle]) -> None:
        self._cycles = cycles

    async def list_by_project(self, project_id: str, limit: int = 30) -> list[Cycle]:
        return [c for c in self._cycles if c.project_id == project_id][:limit]

    async def get(self, cycle_id):
        return next((c for c in self._cycles if c.id == cycle_id), None)

    async def list_recent(self, limit: int = 50):
        return self._cycles[:limit]

    async def save(self, cycle):
        pass


def _make_project(**cfg_overrides) -> Project:
    cfg = ProjectConfig(**cfg_overrides)
    return Project(id="p", repo=RepoUrl("o/r"), config=cfg)


def _cycle(project_id: str, when: datetime, cost: float) -> Cycle:
    return Cycle(
        id=CycleId.generate(),
        project_id=project_id,
        status=CycleStatus.COMPLETED,
        started_at=when,
        completed_at=when,
        total_cost_usd=cost,
    )


class TestBudgetGuard:
    async def test_passes_when_no_caps_set(self):
        guard = BudgetGuard(_FakeCycleRepo([]), now=lambda: _NOW)
        await guard.check(_make_project())  # no raise

    async def test_paused_blocks(self):
        guard = BudgetGuard(_FakeCycleRepo([]), now=lambda: _NOW)
        with pytest.raises(CycleBlocked) as exc:
            await guard.check(_make_project(paused=True))
        assert exc.value.reason == "paused"

    async def test_daily_cap_hit(self):
        cycles = [_cycle("p", _NOW, 3.0), _cycle("p", _NOW, 4.0)]
        guard = BudgetGuard(_FakeCycleRepo(cycles), now=lambda: _NOW)
        with pytest.raises(CycleBlocked, match="daily cap"):
            await guard.check(_make_project(daily_cost_cap_usd=5.0))

    async def test_daily_cap_under_threshold_passes(self):
        cycles = [_cycle("p", _NOW, 1.5)]
        guard = BudgetGuard(_FakeCycleRepo(cycles), now=lambda: _NOW)
        await guard.check(_make_project(daily_cost_cap_usd=5.0))

    async def test_monthly_cap_hit(self):
        # Today + earlier this month
        cycles = [
            _cycle("p", _NOW.replace(day=1), 10.0),
            _cycle("p", _NOW.replace(day=5), 15.0),
        ]
        guard = BudgetGuard(_FakeCycleRepo(cycles), now=lambda: _NOW)
        with pytest.raises(CycleBlocked, match="monthly cap"):
            await guard.check(_make_project(monthly_cost_cap_usd=20.0))

    async def test_previous_month_not_counted(self):
        last_month = _NOW - timedelta(days=40)
        cycles = [_cycle("p", last_month, 100.0)]
        guard = BudgetGuard(_FakeCycleRepo(cycles), now=lambda: _NOW)
        # Last month's spend should not block this month
        await guard.check(_make_project(monthly_cost_cap_usd=50.0))
