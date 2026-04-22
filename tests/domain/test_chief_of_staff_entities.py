"""Phase K domain tests — Chief of Staff entities."""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.domain.chief_of_staff.entities import (
    ArchivedProject,
    BudgetPolicy,
    OnboardingStep,
    RoutingRule,
)
from theswarm.domain.chief_of_staff.value_objects import (
    ArchiveReason,
    BudgetState,
    OnboardingStatus,
    RuleStatus,
)


class TestRoutingRule:
    def test_active_is_enabled(self):
        r = RoutingRule(
            id="r1", pattern="bug", target_role="qa",
            status=RuleStatus.ACTIVE,
        )
        assert r.is_enabled

    def test_disabled_not_enabled(self):
        r = RoutingRule(
            id="r1", pattern="bug", target_role="qa",
            status=RuleStatus.DISABLED,
        )
        assert not r.is_enabled


class TestBudgetPolicy:
    def test_empty_project_id_is_portfolio_wide(self):
        p = BudgetPolicy(id="p1", project_id="")
        assert p.is_portfolio_wide

    def test_project_scoped_not_portfolio_wide(self):
        p = BudgetPolicy(id="p1", project_id="proj-42")
        assert not p.is_portfolio_wide

    def test_exceeded_blocks_cycles(self):
        p = BudgetPolicy(id="p1", state=BudgetState.EXCEEDED)
        assert p.blocks_cycles

    def test_paused_blocks_cycles(self):
        p = BudgetPolicy(id="p1", state=BudgetState.PAUSED)
        assert p.blocks_cycles

    def test_active_does_not_block(self):
        p = BudgetPolicy(id="p1", state=BudgetState.ACTIVE)
        assert not p.blocks_cycles


class TestOnboardingStep:
    def test_complete_is_done(self):
        s = OnboardingStep(
            id="s1", project_id="p", step_name="x",
            status=OnboardingStatus.COMPLETE,
        )
        assert s.is_done

    def test_skipped_is_done(self):
        s = OnboardingStep(
            id="s1", project_id="p", step_name="x",
            status=OnboardingStatus.SKIPPED,
        )
        assert s.is_done

    def test_pending_is_not_done(self):
        s = OnboardingStep(
            id="s1", project_id="p", step_name="x",
            status=OnboardingStatus.PENDING,
        )
        assert not s.is_done


class TestArchivedProject:
    def test_defaults(self):
        a = ArchivedProject(id="a1", project_id="p")
        assert a.reason == ArchiveReason.OTHER
        assert a.memory_frozen is True
        assert isinstance(a.archived_at, datetime)
        assert a.archived_at.tzinfo == timezone.utc
