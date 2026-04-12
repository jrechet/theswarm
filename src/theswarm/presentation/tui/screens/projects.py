"""Projects screen: list and detail view."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from theswarm.application.dto import ProjectDTO
from theswarm.presentation.tui.widgets.project_card import ProjectCard


class ProjectsScreen(Screen):
    """Lists all registered projects."""

    BINDINGS = [
        ("escape", "pop_screen", "Back"),
        ("d", "pop_screen", "Dashboard"),
    ]

    DEFAULT_CSS = """
    ProjectsScreen {
        layout: vertical;
    }
    """

    def __init__(self, projects: list[ProjectDTO] | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._projects = projects or []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(f"[bold]Projects[/bold] ({len(self._projects)})")

        with VerticalScroll():
            if self._projects:
                for p in self._projects:
                    yield ProjectCard(p)
            else:
                yield Static("[dim]No projects registered. Use the web UI to add projects.[/dim]")

        yield Footer()
