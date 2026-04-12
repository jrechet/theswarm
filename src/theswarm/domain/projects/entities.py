"""Entities for the Projects bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.projects.value_objects import (
    Framework,
    RepoUrl,
    TicketSourceType,
)


@dataclass(frozen=True)
class ProjectConfig:
    """Per-project configuration for token budgets and agent behavior."""

    max_daily_stories: int = 3
    token_budget_po: int = 300_000
    token_budget_techlead: int = 600_000
    token_budget_dev: int = 1_000_000
    token_budget_qa: int = 300_000

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
