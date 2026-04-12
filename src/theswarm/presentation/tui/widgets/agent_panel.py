"""Agent status card widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class AgentPanel(Widget):
    """Displays status of a single agent (role, phase, current action)."""

    DEFAULT_CSS = """
    AgentPanel {
        width: 1fr;
        height: auto;
        min-height: 5;
        border: solid $primary;
        padding: 1;
    }
    AgentPanel .agent-name {
        text-style: bold;
        color: $accent;
    }
    AgentPanel .agent-phase {
        color: $text-muted;
    }
    AgentPanel .agent-status-idle {
        color: $text-muted;
    }
    AgentPanel .agent-status-running {
        color: $success;
    }
    """

    def __init__(self, name: str, role: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._agent_name = name
        self._role = role
        self._phase = ""
        self._status = "idle"
        self._action = ""

    def compose(self) -> ComposeResult:
        yield Static(self._agent_name, classes="agent-name", id="agent-name")
        yield Static(f"Role: {self._role}", id="agent-role")
        yield Static("Phase: —", classes="agent-phase", id="agent-phase")
        yield Static("Idle", classes="agent-status-idle", id="agent-status")

    def update_status(self, phase: str = "", status: str = "idle", action: str = "") -> None:
        self._phase = phase
        self._status = status
        self._action = action

        phase_widget = self.query_one("#agent-phase", Static)
        phase_widget.update(f"Phase: {phase or '—'}")

        status_widget = self.query_one("#agent-status", Static)
        display = action if action else status.capitalize()
        status_widget.update(display)
        status_widget.set_classes(f"agent-status-{status}")
