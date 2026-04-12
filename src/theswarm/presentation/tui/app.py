"""Main Textual application for TheSwarm TUI."""

from __future__ import annotations

from textual.app import App

from theswarm.application.dto import DashboardDTO, ProjectDTO
from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.events import AgentActivity, PhaseChanged
from theswarm.domain.events import DomainEvent
from theswarm.presentation.tui.screens.dashboard import DashboardScreen
from theswarm.presentation.tui.screens.projects import ProjectsScreen


class SwarmApp(App):
    """TheSwarm Terminal UI."""

    TITLE = "TheSwarm"
    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        dashboard: DashboardDTO | None = None,
        projects: list[ProjectDTO] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._event_bus = event_bus
        self._dashboard = dashboard
        self._projects = projects or []

    def on_mount(self) -> None:
        # Install screens with data
        self.install_screen(
            DashboardScreen(dashboard=self._dashboard),
            name="dashboard",
        )
        self.install_screen(
            ProjectsScreen(projects=self._projects),
            name="projects",
        )
        self.push_screen("dashboard")

        # Subscribe to events
        if self._event_bus:
            self._event_bus.subscribe(AgentActivity, self._on_agent_activity)
            self._event_bus.subscribe(PhaseChanged, self._on_phase_changed)

    async def _on_agent_activity(self, event: DomainEvent) -> None:
        if not isinstance(event, AgentActivity):
            return
        screen = self.screen
        if isinstance(screen, DashboardScreen):
            screen.on_agent_activity(event.agent, event.action, event.detail)

    async def _on_phase_changed(self, event: DomainEvent) -> None:
        if not isinstance(event, PhaseChanged):
            return
        screen = self.screen
        if isinstance(screen, DashboardScreen):
            screen.on_phase_changed(event.agent, event.phase)
