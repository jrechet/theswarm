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


# The repository this very service is deployed from. A cycle running against
# it is the swarm working on itself, and one thing must not happen there: a
# merge to main redeploys the service, and the redeploy kills the cycle that
# just merged. The TechLead reviews and approves; merging is left to a person
# — or to me, between two cycles.
SELF_REPO = "jrechet/theswarm"


class AgentState(TypedDict, total=False):
    """State flowing through every agent graph."""
    team_id: str
    github_repo: str
    project_id: str
    codenames: dict[str, str]
    phase: str
    # Ports / clients
    github: Any        # GitHubClient
    claude: Any        # ClaudeCLI
    workspace: Any     # str — local clone path
    # Pipeline data
    task: dict | None
    # Task numbers already tried in this cycle, newest last. Owned by the
    # dev loop and mutated in place, so it survives an iteration that raises
    # rather than returning state — which is exactly the case that matters.
    attempted_tasks: list[int]
    # Parallel Dev tasks in one iteration (V2 M5b): the lock serialises the
    # pickers, the list holds what this iteration already claimed. Shared by
    # reference between the Dev graphs of one iteration, never checkpointed.
    pick_lock: Any
    claimed_tasks: list[int]
    branch: str | None
    context: str
    result: str | None
    tokens_used: int
    cost_usd: float
    tests_passed: bool
    test_output: str
    # Why the tests could not run at all (runner missing), "" when they ran.
    # Distinct from tests_passed=False: nothing to repair, nothing to hide.
    tests_unavailable: str
    diff_stat: str
    # Ralph Loop retry accounting. LangGraph drops keys absent from this
    # schema, so omitting these pinned retry_count at 0 and the dev loop
    # retried until the phase timeout (prod cycle 65ab4b0fdf3e).
    retry_count: int
    max_dev_retries: int
    target_issue: int | None  # issue-driven flow: pin the cycle to one GH issue
    deps_fingerprint: str  # hash of requirements.txt last installed
    # A targeted child whose behavior already exists (implemented by a
    # sibling task) is closed instead of merged — nothing to test or PR.
    already_satisfied: bool
    blockers: list[dict]
    pr: dict | None
    # TechLead-specific
    reviews: list[dict]
    merged_prs: list[int]
    held_prs: list[int]  # approved, deliberately left unmerged (SELF_REPO)
    conflicted_prs: list[int]  # approved, unmergeable: sent back for the Dev to merge main
    ci_red_prs: list[int]  # approved, CI red: not merged, sent back to the Dev
    ci_pending_prs: list[int]  # approved, CI still running past the wait: left open
    reviewed_prs: list[str]  # "number@head_sha" reviewed this cycle — once, unless the head moves
    skipped_prs: list[int]  # review call failed — left for the next pass, not marked reviewed
    # QA-specific
    test_counts: dict
    # Why the unit-test run did not produce a result at all (hit its own
    # budget before pytest finished), "" when it ran to completion. Distinct
    # from tests_passed=False: a 0/0 count from a timed-out run must not be
    # read as a vacuous pass.
    unit_tests_not_run_reason: str
    e2e_passed: bool
    e2e_output: str
    e2e_counts: dict
    e2e_failure_excerpt: str  # the lines of a failed E2E run that explain it
    e2e_repaired_from: str  # the setup errors QA rewrote its own E2E file for
    security_scan: dict
    issue_stats: dict
    demo_report: dict | None
    demo_artifacts: list  # list of (Artifact, bytes) tuples from screenshot capture
    video_artifacts: list  # (Artifact, bytes) from record_demo_video → generate_demo_report
    # Why a demo launch (E2E, screenshots or video) never got a running
    # server to talk to — "" when readiness succeeded. Set by whichever
    # launch node hit it first; later nodes that don't fail leave it as-is.
    demo_launch_error: str
    story_preview_urls: dict  # F2 — {pr_number: {"before": url_or_none, "after": url}}
    story_artifacts: dict  # F2 — {pr_number: {"before": [...], "after": [...]}}
    story_videos: dict  # F3 — {pr_number: (Artifact, bytes)}
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

    # Model routing: task category → model short name
    model_routing: dict[str, str] = field(default_factory=lambda: {
        "nlu": "haiku",
        "condensation": "haiku",
        "implementation": "sonnet",
        "review": "sonnet",
        "planning": "sonnet",
        "breakdown": "sonnet",
        "retrospective": "haiku",
        "doc_generation": "haiku",
    })

    # Token budgets (per-agent daily max)
    token_budget: dict[Role, int] = field(default_factory=lambda: {
        Role.PO: 300_000,
        Role.TECHLEAD: 600_000,
        Role.DEV: 1_000_000,
        Role.QA: 300_000,
    })

    # Ralph Loop: max retries when quality gates fail
    max_dev_retries: int = 2

    # Issue-driven flow (P1): when set, the cycle implements THIS GitHub
    # issue and nothing else — breakdown scopes to it, the dev loop pins it
    # then its `Parent: #N` children, and never drains unrelated backlog.
    target_issue: int | None = None

    # Watchdog: idle threshold in seconds (> Claude's 600s timeout)
    watchdog_idle_threshold: float = 720.0
    watchdog_max_warnings: int = 3

    # Context condensation: char threshold before triggering condensation
    condenser_threshold: int = 6000

    # Per-role codenames (e.g. {"po": "Mei", "dev": "Aarav"}). Populated by the
    # caller from the RoleAssignmentService before launching a cycle. Empty in
    # legacy / stub runs — agents fall back to their role label.
    codenames: dict[str, str] = field(default_factory=dict)

    # Project id this cycle runs for. Defaults to ``team_id`` for backwards
    # compat; callers using the v2 project registry should pass the real id.
    project_id: str = ""

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
