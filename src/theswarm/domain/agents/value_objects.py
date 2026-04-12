"""Value objects for the Agents bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentRole(str, Enum):
    PO = "po"
    TECHLEAD = "techlead"
    DEV = "dev"
    QA = "qa"
    IMPROVER = "improver"


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
