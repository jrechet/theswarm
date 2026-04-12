"""Tests for presentation/tui — widget and app tests."""

from __future__ import annotations

import pytest

from theswarm.application.dto import DashboardDTO, ProjectDTO
from theswarm.application.events.bus import EventBus
from theswarm.presentation.tui.app import SwarmApp
from theswarm.presentation.tui.widgets.activity_log import ActivityLog
from theswarm.presentation.tui.widgets.agent_panel import AgentPanel
from theswarm.presentation.tui.widgets.budget_bar import BudgetBar
from theswarm.presentation.tui.widgets.project_card import ProjectCard


# ── Widget unit tests (no App needed) ────────────────────────────


class TestAgentPanel:
    def test_creation(self):
        panel = AgentPanel("PO", "po")
        assert panel._agent_name == "PO"
        assert panel._role == "po"
        assert panel._status == "idle"

    async def test_update_status_mounted(self):
        """Test update_status works when widget is mounted in an app."""
        app = SwarmApp()
        async with app.run_test(size=(80, 24)):
            screen = app.screen
            panel = screen.query_one("#agent-po", AgentPanel)
            panel.update_status(phase="morning", status="running", action="Coding")
            assert panel._phase == "morning"
            assert panel._status == "running"
            assert panel._action == "Coding"


class TestBudgetBar:
    def test_creation(self):
        bar = BudgetBar("po", 300_000, 50_000)
        assert bar._role == "po"
        assert bar._total == 300_000
        assert bar._used == 50_000

    async def test_update_usage_mounted(self):
        """Test update_usage works when widget is mounted in an app."""
        app = SwarmApp()
        async with app.run_test(size=(80, 24)):
            screen = app.screen
            bar = screen.query_one("#budget-dev", BudgetBar)
            bar.update_usage(250_000)
            assert bar._used == 250_000


class TestProjectCard:
    def test_creation(self):
        dto = ProjectDTO(
            id="my-app", repo="o/my-app", default_branch="main",
            framework="fastapi", ticket_source="github", team_channel="",
            schedule="", test_command="", source_dir="src/",
            max_daily_stories=3, created_at="2026-01-01",
        )
        card = ProjectCard(dto)
        assert card._project.id == "my-app"


class TestActivityLog:
    def test_creation(self):
        log = ActivityLog(max_items=50)
        assert log._max_items == 50


# ── App integration tests (using Textual pilot) ─────────────────


class TestSwarmApp:
    def test_app_creation(self):
        app = SwarmApp()
        assert app.TITLE == "TheSwarm"

    def test_app_with_event_bus(self):
        bus = EventBus()
        app = SwarmApp(event_bus=bus)
        assert app._event_bus is bus

    def test_app_with_dashboard(self):
        dashboard = DashboardDTO(
            active_cycles=[], recent_activities=[],
            projects=[], total_cost_today=0.0,
        )
        app = SwarmApp(dashboard=dashboard)
        assert app._dashboard is dashboard

    def test_app_with_projects(self):
        projects = [
            ProjectDTO(
                id="a", repo="o/a", default_branch="main",
                framework="auto", ticket_source="github",
                team_channel="", schedule="", test_command="",
                source_dir="src/", max_daily_stories=3,
                created_at="2026-01-01",
            ),
        ]
        app = SwarmApp(projects=projects)
        assert len(app._projects) == 1

    async def test_app_headless_mount(self):
        """Test that the app can mount headlessly (Textual test mode)."""
        app = SwarmApp()
        async with app.run_test(size=(80, 24)) as pilot:
            # Dashboard screen should be active
            assert app.screen is not None
