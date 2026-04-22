"""Tests for domain/agents — 100% coverage target."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.agents.entities import (
    PORTFOLIO_PROJECT_ID,
    AgentContext,
    AgentExecution,
    RoleAssignment,
)
from theswarm.domain.agents.value_objects import (
    CORE_PROJECT_ROLES,
    DEFAULT_ROLE_SCOPES,
    AgentRole,
    LLMResponse,
    Phase,
    ReviewDecision,
    ReviewResult,
    RoleScope,
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


class TestAgentRoleFromStr:
    def test_aliases(self):
        assert AgentRole.from_str("tech-lead") == AgentRole.TECHLEAD
        assert AgentRole.from_str("Product Owner") == AgentRole.PO
        assert AgentRole.from_str("developer") == AgentRole.DEV
        assert AgentRole.from_str("cos") == AgentRole.CHIEF_OF_STAFF

    def test_direct_values(self):
        assert AgentRole.from_str("scout") == AgentRole.SCOUT
        assert AgentRole.from_str("ARCHITECT") == AgentRole.ARCHITECT

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            AgentRole.from_str("intergalactic_janitor")


class TestRoleScopes:
    def test_core_roles_are_project_scoped(self):
        for role in CORE_PROJECT_ROLES:
            assert DEFAULT_ROLE_SCOPES[role] == RoleScope.PROJECT

    def test_portfolio_roles(self):
        assert DEFAULT_ROLE_SCOPES[AgentRole.SCOUT] == RoleScope.PORTFOLIO
        assert DEFAULT_ROLE_SCOPES[AgentRole.SECURITY] == RoleScope.PORTFOLIO
        assert DEFAULT_ROLE_SCOPES[AgentRole.ARCHITECT] == RoleScope.PORTFOLIO


class TestRoleAssignment:
    def _make(self, **overrides) -> RoleAssignment:
        defaults = {
            "id": RoleAssignment.new_id(),
            "project_id": "demo",
            "role": AgentRole.PO,
            "codename": "Mei",
        }
        defaults.update(overrides)
        return RoleAssignment(**defaults)

    def test_defaults(self):
        a = self._make()
        assert a.is_active is True
        assert a.is_portfolio is False
        assert a.retired_at is None

    def test_is_portfolio(self):
        a = self._make(project_id=PORTFOLIO_PROJECT_ID, role=AgentRole.SCOUT)
        assert a.is_portfolio is True

    def test_display(self):
        a = self._make(codename="Aarav", role=AgentRole.DEV)
        assert a.display() == "Aarav (dev)"

    def test_retire_returns_new_instance(self):
        a = self._make()
        retired = a.retire()
        # Original untouched (immutability).
        assert a.is_active is True
        assert retired.is_active is False
        assert retired.retired_at is not None

    def test_retire_with_explicit_timestamp(self):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        a = self._make().retire(at=ts)
        assert a.retired_at == ts

    def test_new_id_is_unique_and_short(self):
        ids = {RoleAssignment.new_id() for _ in range(10)}
        assert len(ids) == 10
        for i in ids:
            assert len(i) == 16
