"""Token budget progress bar widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import ProgressBar, Static


class BudgetBar(Widget):
    """Displays token budget usage for a role."""

    DEFAULT_CSS = """
    BudgetBar {
        height: 3;
        padding: 0 1;
    }
    BudgetBar .budget-label {
        width: 100%;
    }
    """

    def __init__(self, role: str, total: int, used: int = 0, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._role = role
        self._total = total
        self._used = used

    def compose(self) -> ComposeResult:
        pct = (self._used / self._total * 100) if self._total > 0 else 0
        label = f"{self._role}: {self._used:,} / {self._total:,} ({pct:.0f}%)"
        yield Static(label, classes="budget-label", id="budget-label")
        yield ProgressBar(total=self._total, show_eta=False, show_percentage=False, id="budget-progress")

    def on_mount(self) -> None:
        bar = self.query_one("#budget-progress", ProgressBar)
        bar.advance(self._used)

    def update_usage(self, used: int) -> None:
        self._used = used
        pct = (used / self._total * 100) if self._total > 0 else 0
        label = f"{self._role}: {used:,} / {self._total:,} ({pct:.0f}%)"
        self.query_one("#budget-label", Static).update(label)
        bar = self.query_one("#budget-progress", ProgressBar)
        bar.update(total=self._total, progress=used)
