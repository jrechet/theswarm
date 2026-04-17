"""Tests for the autonomous cycle mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.config import CycleConfig
from theswarm.cycle import _check_project_done, run_autonomous


@pytest.fixture
def stub_config():
    """CycleConfig in stub mode (no SWARM_GITHUB_REPO)."""
    return CycleConfig(github_repo="", team_id="test")


@pytest.fixture
def real_config():
    """CycleConfig in real mode."""
    return CycleConfig(github_repo="owner/repo", team_id="test")


class TestCheckProjectDone:
    async def test_stub_mode_is_always_done(self, stub_config):
        is_done, reason = await _check_project_done(stub_config)
        assert is_done
        assert "Stub" in reason

    async def test_all_closed_no_prs(self, real_config):
        with patch("theswarm.tools.github.GitHubClient") as mock_cls:
            gh = AsyncMock()
            gh.get_issues = AsyncMock(return_value=[])
            gh.get_open_prs = AsyncMock(return_value=[])
            mock_cls.return_value = gh

            is_done, reason = await _check_project_done(real_config)
            assert is_done
            assert "All issues closed" in reason

    async def test_open_backlog_not_done(self, real_config):
        with patch("theswarm.tools.github.GitHubClient") as mock_cls:
            gh = AsyncMock()
            gh.get_issues = AsyncMock(return_value=[
                {"number": 1, "title": "Story 1", "labels": ["status:backlog"]},
            ])
            gh.get_open_prs = AsyncMock(return_value=[])
            mock_cls.return_value = gh

            is_done, reason = await _check_project_done(real_config)
            assert not is_done
            assert "backlog=1" in reason

    async def test_open_prs_not_done(self, real_config):
        with patch("theswarm.tools.github.GitHubClient") as mock_cls:
            gh = AsyncMock()
            gh.get_issues = AsyncMock(return_value=[])
            gh.get_open_prs = AsyncMock(return_value=[
                {"number": 10, "title": "PR 10"},
            ])
            mock_cls.return_value = gh

            is_done, reason = await _check_project_done(real_config)
            assert not is_done
            assert "open_prs=1" in reason


class TestRunAutonomous:
    async def test_stops_after_max_cycles(self, stub_config):
        """In stub mode, cycles produce stub results. Loop should run and stop."""
        result = await run_autonomous(stub_config, max_cycles=2)
        # Stub mode cycles complete immediately
        assert result["cycles_run"] <= 2

    async def test_stops_when_project_done(self, real_config):
        """Autonomous mode stops when _check_project_done returns True."""
        cycle_call_count = 0

        async def fake_daily_cycle(config, on_progress=None):
            nonlocal cycle_call_count
            cycle_call_count += 1
            return {
                "date": "2026-04-16",
                "tokens": 1000,
                "cost_usd": 0.50,
                "prs": [],
                "reviews": [],
                "demo_report": {"overall_status": "green", "screenshot_count": 2},
                "daily_report": "",
            }

        check_calls = 0

        async def fake_check_done(config):
            nonlocal check_calls
            check_calls += 1
            # Done after first cycle
            return True, "All issues closed, no open PRs"

        with patch("theswarm.cycle.run_daily_cycle", side_effect=fake_daily_cycle), \
             patch("theswarm.cycle._check_project_done", side_effect=fake_check_done):
            result = await run_autonomous(real_config, max_cycles=5)

        assert result["cycles_run"] == 1  # only 1 cycle before completion detected
        assert result["project_done"] is True
        assert result["total_cost_usd"] == 0.50

    async def test_continues_on_transient_failure(self, real_config):
        """Autonomous mode continues past failures."""
        call_count = 0
        check_count = 0

        async def flaky_cycle(config, on_progress=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Transient error")
            return {
                "date": "2026-04-16",
                "tokens": 500,
                "cost_usd": 0.25,
                "prs": [],
                "reviews": [],
                "demo_report": {"overall_status": "yellow", "screenshot_count": 0},
                "daily_report": "",
            }

        async def done_after_second(config):
            nonlocal check_count
            check_count += 1
            # Not done after first failure, done after second succeeds
            if check_count <= 1:
                return False, "backlog=1 ready=0 in_progress=0 unlabeled=0 open_prs=0"
            return True, "All done"

        with patch("theswarm.cycle.run_daily_cycle", side_effect=flaky_cycle), \
             patch("theswarm.cycle._check_project_done", side_effect=done_after_second):
            result = await run_autonomous(real_config, max_cycles=5)

        # Cycle 1 failed, cycle 2 check found work remaining, cycle 2 succeeded,
        # cycle 3 check found done
        assert call_count == 2  # two calls to run_daily_cycle
        assert result["cycles_run"] == 1  # only 1 successful cycle result
        assert result["project_done"] is True
