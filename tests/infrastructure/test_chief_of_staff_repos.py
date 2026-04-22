"""Phase K infrastructure tests — Chief of Staff repos."""

from __future__ import annotations

import pytest

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
from theswarm.infrastructure.chief_of_staff.archive_repo import (
    SQLiteArchivedProjectRepository,
)
from theswarm.infrastructure.chief_of_staff.budget_repo import (
    SQLiteBudgetPolicyRepository,
)
from theswarm.infrastructure.chief_of_staff.onboarding_repo import (
    SQLiteOnboardingStepRepository,
)
from theswarm.infrastructure.chief_of_staff.routing_repo import (
    SQLiteRoutingRuleRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "cos.db"))
    yield conn
    await conn.close()


class TestRoutingRuleRepo:
    async def test_upsert_preserves_id_on_same_pattern(self, db):
        repo = SQLiteRoutingRuleRepository(db)
        r1 = RoutingRule(id="r1", pattern="bug", target_role="qa")
        got1 = await repo.upsert(r1)
        assert got1.id == "r1"

        r2 = RoutingRule(
            id="r2", pattern="bug", target_role="techlead", priority=50,
        )
        got2 = await repo.upsert(r2)
        assert got2.id == "r1"
        assert got2.target_role == "techlead"
        assert got2.priority == 50

    async def test_list_active_excludes_disabled(self, db):
        repo = SQLiteRoutingRuleRepository(db)
        await repo.upsert(RoutingRule(
            id="r1", pattern="a", target_role="qa",
            status=RuleStatus.ACTIVE,
        ))
        await repo.upsert(RoutingRule(
            id="r2", pattern="b", target_role="dev",
            status=RuleStatus.DISABLED,
        ))
        active = await repo.list_active()
        assert len(active) == 1
        assert active[0].pattern == "a"


class TestBudgetPolicyRepo:
    async def test_upsert_preserves_id_on_same_project(self, db):
        repo = SQLiteBudgetPolicyRepository(db)
        p1 = BudgetPolicy(id="p1", project_id="proj", daily_tokens_limit=1000)
        await repo.upsert(p1)
        p2 = BudgetPolicy(
            id="p2", project_id="proj", daily_tokens_limit=2000,
            state=BudgetState.EXCEEDED,
        )
        got = await repo.upsert(p2)
        assert got.id == "p1"
        assert got.daily_tokens_limit == 2000
        assert got.state == BudgetState.EXCEEDED

    async def test_get_for_portfolio(self, db):
        repo = SQLiteBudgetPolicyRepository(db)
        p = BudgetPolicy(id="p1", project_id="", daily_cost_usd_limit=50.0)
        await repo.upsert(p)
        got = await repo.get_for_project("")
        assert got is not None
        assert got.is_portfolio_wide
        assert got.daily_cost_usd_limit == 50.0


class TestOnboardingStepRepo:
    async def test_upsert_preserves_id_on_same_step(self, db):
        repo = SQLiteOnboardingStepRepository(db)
        s1 = OnboardingStep(
            id="s1", project_id="p", step_name="create_roster", order=10,
        )
        await repo.upsert(s1)
        s2 = OnboardingStep(
            id="s2", project_id="p", step_name="create_roster", order=10,
            status=OnboardingStatus.COMPLETE,
        )
        got = await repo.upsert(s2)
        assert got.id == "s1"
        assert got.status == OnboardingStatus.COMPLETE

    async def test_list_for_project_orders_by_step_order(self, db):
        repo = SQLiteOnboardingStepRepository(db)
        await repo.upsert(OnboardingStep(
            id="s1", project_id="p", step_name="b", order=20,
        ))
        await repo.upsert(OnboardingStep(
            id="s2", project_id="p", step_name="a", order=10,
        ))
        rows = await repo.list_for_project("p")
        assert [r.step_name for r in rows] == ["a", "b"]


class TestArchivedProjectRepo:
    async def test_add_and_list(self, db):
        repo = SQLiteArchivedProjectRepository(db)
        a = ArchivedProject(
            id="a1", project_id="retired",
            reason=ArchiveReason.SHIPPED, export_path="/tmp/x.json",
        )
        await repo.add(a)
        rows = await repo.list_all()
        assert len(rows) == 1
        assert rows[0].reason == ArchiveReason.SHIPPED

        got = await repo.get_for_project("retired")
        assert got is not None
        assert got.export_path == "/tmp/x.json"
