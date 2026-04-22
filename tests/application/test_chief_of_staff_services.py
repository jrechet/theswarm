"""Phase K application tests — Chief of Staff services."""

from __future__ import annotations

import pytest

from theswarm.application.services.chief_of_staff import (
    ArchiveService,
    BudgetPolicyService,
    OnboardingService,
    RoutingService,
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
    conn = await init_db(str(tmp_path / "cos_svc.db"))
    yield conn
    await conn.close()


class TestRoutingService:
    async def test_upsert_and_match_substring(self, db):
        svc = RoutingService(SQLiteRoutingRuleRepository(db))
        await svc.upsert(
            pattern="bug", target_role="qa", priority=10,
        )
        await svc.upsert(
            pattern="security", target_role="security_agent", priority=5,
        )
        hit = await svc.match("found a BUG in login")
        assert hit is not None
        assert hit.target_role == "qa"

        hit2 = await svc.match("this looks like a Security issue")
        assert hit2 is not None
        assert hit2.target_role == "security_agent"

    async def test_match_regex(self, db):
        svc = RoutingService(SQLiteRoutingRuleRepository(db))
        await svc.upsert(
            pattern="re:deploy.*prod", target_role="sre",
        )
        hit = await svc.match("can we deploy v2 to prod tonight?")
        assert hit is not None
        assert hit.target_role == "sre"

    async def test_match_priority_order(self, db):
        svc = RoutingService(SQLiteRoutingRuleRepository(db))
        await svc.upsert(pattern="deploy", target_role="sre", priority=100)
        await svc.upsert(
            pattern="prod deploy", target_role="release", priority=10,
        )
        hit = await svc.match("please handle this prod deploy")
        assert hit.target_role == "release"

    async def test_disable(self, db):
        svc = RoutingService(SQLiteRoutingRuleRepository(db))
        await svc.upsert(pattern="bug", target_role="qa")
        disabled = await svc.disable("bug")
        assert disabled.status == RuleStatus.DISABLED
        assert (await svc.match("bug here")) is None

    async def test_disable_missing_raises(self, db):
        svc = RoutingService(SQLiteRoutingRuleRepository(db))
        with pytest.raises(ValueError):
            await svc.disable("missing")


class TestBudgetPolicyService:
    async def test_upsert_clamps_negatives(self, db):
        svc = BudgetPolicyService(SQLiteBudgetPolicyRepository(db))
        p = await svc.upsert(
            project_id="", daily_tokens_limit=-5,
            daily_cost_usd_limit=-10.0,
        )
        assert p.daily_tokens_limit == 0
        assert p.daily_cost_usd_limit == 0.0

    async def test_set_state(self, db):
        svc = BudgetPolicyService(SQLiteBudgetPolicyRepository(db))
        await svc.upsert(project_id="proj", daily_tokens_limit=1000)
        updated = await svc.set_state("proj", BudgetState.EXCEEDED)
        assert updated.state == BudgetState.EXCEEDED
        assert updated.blocks_cycles

    async def test_set_state_missing_raises(self, db):
        svc = BudgetPolicyService(SQLiteBudgetPolicyRepository(db))
        with pytest.raises(ValueError):
            await svc.set_state("missing", BudgetState.EXCEEDED)


class TestOnboardingService:
    async def test_seed_defaults_creates_all_steps(self, db):
        svc = OnboardingService(SQLiteOnboardingStepRepository(db))
        steps = await svc.seed_defaults("p1")
        assert len(steps) == len(OnboardingService.DEFAULT_STEPS)

    async def test_seed_defaults_is_idempotent(self, db):
        svc = OnboardingService(SQLiteOnboardingStepRepository(db))
        first = await svc.seed_defaults("p1")
        second = await svc.seed_defaults("p1")
        assert [s.id for s in first] == [s.id for s in second]

    async def test_mark_status_sets_completed_at(self, db):
        svc = OnboardingService(SQLiteOnboardingStepRepository(db))
        await svc.seed_defaults("p1")
        updated = await svc.mark_status(
            "p1", "create_roster", OnboardingStatus.COMPLETE,
            note="done by Ada",
        )
        assert updated.status == OnboardingStatus.COMPLETE
        assert updated.completed_at is not None

    async def test_mark_missing_raises(self, db):
        svc = OnboardingService(SQLiteOnboardingStepRepository(db))
        with pytest.raises(ValueError):
            await svc.mark_status(
                "p1", "nope", OnboardingStatus.COMPLETE,
            )

    async def test_progress_counter(self, db):
        svc = OnboardingService(SQLiteOnboardingStepRepository(db))
        await svc.seed_defaults("p1")
        await svc.mark_status(
            "p1", "create_roster", OnboardingStatus.COMPLETE,
        )
        await svc.mark_status(
            "p1", "assign_codenames", OnboardingStatus.SKIPPED,
        )
        done, total = await svc.progress("p1")
        assert done == 2
        assert total == len(OnboardingService.DEFAULT_STEPS)


class TestArchiveService:
    async def test_archive_and_is_archived(self, db):
        svc = ArchiveService(SQLiteArchivedProjectRepository(db))
        a = await svc.archive(
            project_id="retired", reason=ArchiveReason.SHIPPED,
            export_path="/tmp/x.json",
        )
        assert a.reason == ArchiveReason.SHIPPED
        assert await svc.is_archived("retired")
        assert not await svc.is_archived("still-active")
