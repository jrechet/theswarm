"""Scrolling activity feed widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static


class ActivityItem(Static):
    """A single activity entry."""

    DEFAULT_CSS = """
    ActivityItem {
        padding: 0 1;
        margin: 0;
        height: auto;
    }
    """


class ActivityLog(Widget):
    """Scrolling list of agent activities."""

    DEFAULT_CSS = """
    ActivityLog {
        height: 100%;
        border: solid $primary;
    }
    """

    def __init__(self, max_items: int = 200, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._max_items = max_items

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="activity-scroll")

    def add_activity(self, agent: str, action: str, detail: str = "") -> None:
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        text = f"[bold]{agent}[/bold] {action}"
        if detail:
            text += f" — {detail}"
        item = ActivityItem(text)
        scroll.mount(item)

        # Trim old items
        children = list(scroll.children)
        while len(children) > self._max_items:
            children[0].remove()
            children = children[1:]

        scroll.scroll_end(animate=False)

    def clear(self) -> None:
        scroll = self.query_one("#activity-scroll", VerticalScroll)
        scroll.remove_children()
