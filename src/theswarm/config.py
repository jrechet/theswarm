"""Configuration and base types for the SWARM MVP."""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass, field
from typing import Any, TypedDict


class Role(str, enum.Enum):
    PO = "po"
    TECHLEAD = "techlead"
    DEV = "dev"
    QA = "qa"


class Phase(str, enum.Enum):
    MORNING = "morning"          # PO plans, TechLead breaks down
    DEVELOPMENT = "development"  # Dev implements, TechLead reviews
    DEMO = "demo"                # QA runs tests + generates demo
    EVENING = "evening"          # PO validates demo + writes report


class AgentState(TypedDict, total=False):
    """State flowing through every agent graph."""
    team_id: str
    github_repo: str
    phase: str
    # Ports / clients
    llm: Any           # reserved for future langchain model
    github: Any        # GitHubClient
    claude: Any        # ClaudeCLI
    workspace: Any     # str — local clone path
    # Pipeline data
    task: dict | None
    branch: str | None
    context: str
    result: str | None
    tokens_used: int
    cost_usd: float
    tests_passed: bool
    test_output: str
    diff_stat: str
    blockers: list[dict]
    pr: dict | None
    # TechLead-specific
    reviews: list[dict]
    merged_prs: list[int]
    # QA-specific
    test_counts: dict
    e2e_passed: bool
    e2e_output: str
    e2e_counts: dict
    security_scan: dict
    issue_stats: dict
    demo_report: dict | None
    # PO-specific
    daily_plan: str
    daily_report: str


@dataclass
class CycleConfig:
    """Everything needed to run one daily cycle."""
    github_repo: str
    team_id: str = "alpha"
    claude_model: str = "sonnet"
    workspace_dir: str = ""  # auto-set if empty

    # Token budgets (per-agent daily max)
    token_budget: dict[Role, int] = field(default_factory=lambda: {
        Role.PO: 300_000,
        Role.TECHLEAD: 600_000,
        Role.DEV: 1_000_000,
        Role.QA: 300_000,
    })

    def __post_init__(self) -> None:
        if not self.workspace_dir and self.github_repo:
            repo_name = self.github_repo.split("/")[-1] if self.github_repo else "workspace"
            self.workspace_dir = os.path.join(
                os.path.expanduser("~"), ".swarm-workspaces", self.team_id, repo_name,
            )

    @property
    def is_real_mode(self) -> bool:
        return bool(self.github_repo)

    @property
    def repo_clone_url(self) -> str:
        if not self.github_repo:
            return ""
        return f"https://github.com/{self.github_repo}.git"

    @classmethod
    def from_env(cls) -> CycleConfig:
        return cls(
            github_repo=os.environ.get("SWARM_GITHUB_REPO", ""),
            team_id=os.environ.get("SWARM_TEAM_ID", "alpha"),
            claude_model=os.environ.get("SWARM_CLAUDE_MODEL", "sonnet"),
            workspace_dir=os.environ.get("SWARM_WORKSPACE_DIR", ""),
        )
