"""Entities for the Projects bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from theswarm.domain.projects.value_objects import (
    Framework,
    RepoUrl,
    TicketSourceType,
)

_EFFORT_VALUES = frozenset({"low", "medium", "high"})

_DEFAULT_MODELS: dict[str, str] = {
    "po": "sonnet",
    "techlead": "sonnet",
    "dev": "sonnet",
    "qa": "haiku",
}


@dataclass(frozen=True)
class ProjectConfig:
    """Per-project configuration for token budgets and agent behavior."""

    max_daily_stories: int = 3
    token_budget_po: int = 300_000
    token_budget_techlead: int = 600_000
    token_budget_dev: int = 1_000_000
    token_budget_qa: int = 300_000
    # Sprint B — dashboard-driven controls
    effort: str = "medium"  # low | medium | high
    models: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_MODELS))
    daily_cost_cap_usd: float = 0.0  # 0 = no cap
    daily_tokens_cap: int = 0
    monthly_cost_cap_usd: float = 0.0
    paused: bool = False
    # Sprint C — live preview iframe
    preview_url_template: str = ""

    def __post_init__(self) -> None:
        if self.effort not in _EFFORT_VALUES:
            raise ValueError(
                f"effort must be one of {sorted(_EFFORT_VALUES)}, got {self.effort!r}",
            )
        if self.daily_cost_cap_usd < 0:
            raise ValueError("daily_cost_cap_usd must be >= 0")
        if self.daily_tokens_cap < 0:
            raise ValueError("daily_tokens_cap must be >= 0")
        if self.monthly_cost_cap_usd < 0:
            raise ValueError("monthly_cost_cap_usd must be >= 0")

    @property
    def token_budgets(self) -> dict[str, int]:
        return {
            "po": self.token_budget_po,
            "techlead": self.token_budget_techlead,
            "dev": self.token_budget_dev,
            "qa": self.token_budget_qa,
        }


@dataclass(frozen=True)
class Project:
    """A managed software project."""

    id: str
    repo: RepoUrl
    default_branch: str = "main"
    framework: Framework = Framework.AUTO
    ticket_source: TicketSourceType = TicketSourceType.GITHUB
    team_channel: str = ""
    schedule: str = ""
    test_command: str = ""
    source_dir: str = "src/"
    config: ProjectConfig = field(default_factory=ProjectConfig)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def with_detected_framework(
        self,
        framework: Framework,
        test_command: str,
        source_dir: str,
        default_branch: str,
    ) -> Project:
        """Return a new Project with auto-detected values applied."""
        return Project(
            id=self.id,
            repo=self.repo,
            default_branch=default_branch or self.default_branch,
            framework=framework,
            ticket_source=self.ticket_source,
            team_channel=self.team_channel,
            schedule=self.schedule,
            test_command=test_command or self.test_command,
            source_dir=source_dir or self.source_dir,
            config=self.config,
            created_at=self.created_at,
        )

    def with_config(self, config: ProjectConfig) -> Project:
        """Return a new Project with its config replaced."""
        return replace(self, config=config)
