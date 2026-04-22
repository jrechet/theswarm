"""Value objects for the Agents bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentRole(str, Enum):
    # Core four (existing pipeline).
    PO = "po"
    TECHLEAD = "techlead"
    DEV = "dev"
    QA = "qa"
    IMPROVER = "improver"
    # Specialist roles introduced with the roster system.
    SCOUT = "scout"
    DESIGNER = "designer"
    SRE = "sre"
    SECURITY = "security"
    ANALYST = "analyst"
    WRITER = "writer"
    RELEASE = "release"
    ARCHITECT = "architect"
    CHIEF_OF_STAFF = "chief_of_staff"

    @classmethod
    def from_str(cls, value: str) -> AgentRole:
        """Tolerant parse that accepts common synonyms."""
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "tech_lead": cls.TECHLEAD,
            "product_owner": cls.PO,
            "developer": cls.DEV,
            "quality": cls.QA,
            "cos": cls.CHIEF_OF_STAFF,
            "chief": cls.CHIEF_OF_STAFF,
        }
        if key in aliases:
            return aliases[key]
        return cls(key)


class RoleScope(str, Enum):
    """Whether a role attaches to a single project or to the whole portfolio."""

    PROJECT = "project"
    PORTFOLIO = "portfolio"


DEFAULT_ROLE_SCOPES: dict[AgentRole, RoleScope] = {
    AgentRole.PO: RoleScope.PROJECT,
    AgentRole.TECHLEAD: RoleScope.PROJECT,
    AgentRole.DEV: RoleScope.PROJECT,
    AgentRole.QA: RoleScope.PROJECT,
    AgentRole.IMPROVER: RoleScope.PROJECT,
    AgentRole.DESIGNER: RoleScope.PROJECT,
    AgentRole.ANALYST: RoleScope.PROJECT,
    AgentRole.WRITER: RoleScope.PROJECT,
    AgentRole.RELEASE: RoleScope.PROJECT,
    AgentRole.SCOUT: RoleScope.PORTFOLIO,
    AgentRole.SRE: RoleScope.PORTFOLIO,
    AgentRole.SECURITY: RoleScope.PORTFOLIO,
    AgentRole.ARCHITECT: RoleScope.PORTFOLIO,
    AgentRole.CHIEF_OF_STAFF: RoleScope.PORTFOLIO,
}

# Roles that every project gets by default at creation time.
CORE_PROJECT_ROLES: tuple[AgentRole, ...] = (
    AgentRole.PO,
    AgentRole.TECHLEAD,
    AgentRole.DEV,
    AgentRole.QA,
)


class Phase(str, Enum):
    MORNING = "morning"
    BREAKDOWN = "breakdown"
    DEVELOPMENT = "development"
    REVIEW = "review"
    DEMO = "demo"
    EVENING = "evening"
    IMPROVEMENT = "improvement"


class ReviewDecision(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    COMMENT = "comment"


@dataclass(frozen=True)
class TaskResult:
    """Result of a dev agent implementing a task."""

    task_number: int
    branch: str
    files_changed: int
    lines_added: int
    lines_removed: int
    tests_passed: bool
    test_output: str
    pr_number: int | None = None
    pr_url: str = ""


@dataclass(frozen=True)
class ReviewResult:
    """Result of a TechLead review."""

    pr_number: int
    decision: ReviewDecision
    summary: str
    comments: tuple[str, ...] = ()


@dataclass(frozen=True)
class LLMResponse:
    """Response from an LLM backend."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
