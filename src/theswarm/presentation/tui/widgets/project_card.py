"""Project summary widget for TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from theswarm.application.dto import ProjectDTO


class ProjectCard(Widget):
    """Compact project info card."""

    DEFAULT_CSS = """
    ProjectCard {
        height: auto;
        min-height: 4;
        border: solid $primary;
        padding: 1;
        margin: 0 0 1 0;
    }
    ProjectCard .project-id {
        text-style: bold;
    }
    ProjectCard .project-meta {
        color: $text-muted;
    }
    """

    def __init__(self, project: ProjectDTO, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._project = project

    def compose(self) -> ComposeResult:
        p = self._project
        yield Static(p.id, classes="project-id")
        yield Static(f"{p.repo} | {p.framework} | {p.ticket_source}", classes="project-meta")
        yield Static(f"Max {p.max_daily_stories} stories/day", classes="project-meta")
