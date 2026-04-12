"""Value objects for the Chat bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IntentAction(str, Enum):
    CREATE_STORIES = "create_stories"
    RUN_CYCLE = "run_cycle"
    SHOW_STATUS = "show_status"
    SHOW_PLAN = "show_plan"
    SHOW_REPORT = "show_report"
    LIST_STORIES = "list_stories"
    LIST_REPOS = "list_repos"
    LIST_PROJECTS = "list_projects"
    ADD_PROJECT = "add_project"
    SCHEDULE = "schedule"
    IMPROVEMENTS = "improvements"
    PING = "ping"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Intent:
    """Parsed user intent from NLU."""

    action: IntentAction
    confidence: float
    raw_text: str = ""
    params: dict = field(default_factory=dict)

    @property
    def is_confident(self) -> bool:
        return self.confidence >= 0.35 and self.action != IntentAction.UNKNOWN


@dataclass(frozen=True)
class ButtonAction:
    """An interactive button in a chat message."""

    id: str
    name: str
    style: str = "default"  # "default", "good", "danger"
