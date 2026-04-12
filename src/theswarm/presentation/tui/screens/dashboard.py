"""Dashboard screen: live agent activity + project overview."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from theswarm.application.dto import DashboardDTO
from theswarm.presentation.tui.widgets.activity_log import ActivityLog
from theswarm.presentation.tui.widgets.agent_panel import AgentPanel
from theswarm.presentation.tui.widgets.budget_bar import BudgetBar


class DashboardScreen(Screen):
    """Main dashboard with agent panels, activity feed, and budgets."""

    BINDINGS = [
        ("p", "push_screen('projects')", "Projects"),
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    #agents-row {
        height: auto;
        min-height: 7;
    }
    #main-content {
        height: 1fr;
    }
    #activity-panel {
        width: 2fr;
    }
    #sidebar {
        width: 1fr;
    }
    """

    def __init__(self, dashboard: DashboardDTO | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._dashboard = dashboard

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="agents-row"):
            yield AgentPanel("PO", "po", id="agent-po")
            yield AgentPanel("TechLead", "techlead", id="agent-techlead")
            yield AgentPanel("Dev", "dev", id="agent-dev")
            yield AgentPanel("QA", "qa", id="agent-qa")

        with Horizontal(id="main-content"):
            with Vertical(id="activity-panel"):
                yield Static("[bold]Activity Feed[/bold]")
                yield ActivityLog(id="activity-log")

            with Vertical(id="sidebar"):
                yield Static("[bold]Token Budgets[/bold]")
                yield BudgetBar("PO", 300_000, id="budget-po")
                yield BudgetBar("TechLead", 600_000, id="budget-techlead")
                yield BudgetBar("Dev", 1_000_000, id="budget-dev")
                yield BudgetBar("QA", 300_000, id="budget-qa")

                if self._dashboard:
                    yield Static(f"\n[bold]Projects:[/bold] {len(self._dashboard.projects)}")
                    yield Static(f"[bold]Active Cycles:[/bold] {len(self._dashboard.active_cycles)}")
                    yield Static(f"[bold]Cost Today:[/bold] ${self._dashboard.total_cost_today:.2f}")

        yield Footer()

    def on_agent_activity(self, agent: str, action: str, detail: str = "") -> None:
        """Called by the app when an AgentActivity event arrives."""
        log = self.query_one("#activity-log", ActivityLog)
        log.add_activity(agent, action, detail)

    def on_phase_changed(self, agent: str, phase: str) -> None:
        """Called by the app when a PhaseChanged event arrives."""
        agent_id = f"agent-{agent}"
        try:
            panel = self.query_one(f"#{agent_id}", AgentPanel)
            panel.update_status(phase=phase, status="running")
        except Exception:
            pass

    def on_budget_update(self, role: str, used: int) -> None:
        """Called by the app when budget usage changes."""
        budget_id = f"budget-{role}"
        try:
            bar = self.query_one(f"#{budget_id}", BudgetBar)
            bar.update_usage(used)
        except Exception:
            pass
