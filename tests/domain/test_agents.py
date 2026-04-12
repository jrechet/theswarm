"""Tests for domain/agents — 100% coverage target."""

from __future__ import annotations

import pytest

from theswarm.domain.agents.entities import AgentContext, AgentExecution
from theswarm.domain.agents.value_objects import (
    AgentRole,
    LLMResponse,
    Phase,
    ReviewDecision,
    ReviewResult,
    TaskResult,
)


class TestAgentRole:
    def test_values(self):
        assert AgentRole.PO == "po"
        assert AgentRole.TECHLEAD == "techlead"
        assert AgentRole.DEV == "dev"
        assert AgentRole.QA == "qa"
        assert AgentRole.IMPROVER == "improver"


class TestPhase:
    def test_values(self):
        assert Phase.MORNING == "morning"
        assert Phase.BREAKDOWN == "breakdown"
        assert Phase.DEVELOPMENT == "development"
        assert Phase.REVIEW == "review"
        assert Phase.DEMO == "demo"
        assert Phase.EVENING == "evening"
        assert Phase.IMPROVEMENT == "improvement"


class TestReviewDecision:
    def test_values(self):
        assert ReviewDecision.APPROVE == "approve"
        assert ReviewDecision.REQUEST_CHANGES == "request_changes"
        assert ReviewDecision.COMMENT == "comment"


class TestTaskResult:
    def test_creation(self):
        r = TaskResult(
            task_number=42, branch="dev/us-042", files_changed=3,
            lines_added=100, lines_removed=20, tests_passed=True,
            test_output="14 passed", pr_number=47, pr_url="https://example.com/pr/47",
        )
        assert r.task_number == 42
        assert r.pr_number == 47

    def test_defaults(self):
        r = TaskResult(
            task_number=1, branch="b", files_changed=0,
            lines_added=0, lines_removed=0, tests_passed=False, test_output="",
        )
        assert r.pr_number is None
        assert r.pr_url == ""


class TestReviewResult:
    def test_creation(self):
        r = ReviewResult(pr_number=42, decision=ReviewDecision.APPROVE, summary="LGTM")
        assert r.decision == ReviewDecision.APPROVE
        assert r.comments == ()

    def test_with_comments(self):
        r = ReviewResult(
            pr_number=42, decision=ReviewDecision.REQUEST_CHANGES,
            summary="Needs work", comments=("Fix lint", "Add test"),
        )
        assert len(r.comments) == 2


class TestLLMResponse:
    def test_creation(self):
        r = LLMResponse(text="hello", input_tokens=10, output_tokens=5, cost_usd=0.01)
        assert r.text == "hello"
        assert r.model == ""


class TestAgentContext:
    def test_empty(self):
        ctx = AgentContext()
        assert ctx.is_empty is True

    def test_not_empty(self):
        ctx = AgentContext(golden_rules="be good")
        assert ctx.is_empty is False


class TestAgentExecution:
    def test_creation(self):
        e = AgentExecution(role=AgentRole.DEV, phase=Phase.DEVELOPMENT, project_id="p1")
        assert e.succeeded is False
        assert e.duration_seconds is None
        assert e.error is None

    def test_complete(self):
        e = AgentExecution(role=AgentRole.DEV, phase=Phase.DEVELOPMENT, project_id="p1")
        e2 = e.complete("Implemented US-042", tokens=5000, cost=0.50)
        assert e2.succeeded is True
        assert e2.result_summary == "Implemented US-042"
        assert e2.tokens_used == 5000
        assert e2.duration_seconds is not None
        assert e2.duration_seconds >= 0

    def test_fail(self):
        e = AgentExecution(role=AgentRole.QA, phase=Phase.DEMO, project_id="p1")
        e2 = e.fail("Playwright crashed")
        assert e2.succeeded is False
        assert e2.error == "Playwright crashed"
        assert e2.completed_at is not None
