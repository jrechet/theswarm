"""Phase F infrastructure tests for QA-enrichments SQLite repositories."""

from __future__ import annotations

import pytest

from theswarm.domain.qa.entities import (
    FlakeRecord,
    OutcomeCard,
    QualityGate,
    QuarantineEntry,
    StoryAcceptance,
    TestPlan,
)
from theswarm.domain.qa.value_objects import (
    GateName,
    GateStatus,
    QuarantineStatus,
    TestArchetype,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.qa import (
    SQLiteFlakeRecordRepository,
    SQLiteOutcomeCardRepository,
    SQLiteQualityGateRepository,
    SQLiteQuarantineRepository,
    SQLiteTestPlanRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "qa.db"))
    yield conn
    await conn.close()


class TestPlanRepoIntegration:
    async def test_upsert_creates_then_updates(self, db):
        repo = SQLiteTestPlanRepository(db)
        plan = TestPlan(
            id="plan_1",
            project_id="p",
            task_id="T1",
            required=(TestArchetype.UNIT, TestArchetype.E2E),
            produced=(TestArchetype.UNIT,),
        )
        await repo.upsert(plan)

        updated = TestPlan(
            id="plan_1",
            project_id="p",
            task_id="T1",
            required=(TestArchetype.UNIT, TestArchetype.E2E),
            produced=(TestArchetype.UNIT, TestArchetype.E2E),
            notes="fully covered",
        )
        await repo.upsert(updated)

        got = await repo.get_for_task("p", "T1")
        assert got is not None
        assert got.satisfied is True
        assert got.notes == "fully covered"

    async def test_list_for_project(self, db):
        repo = SQLiteTestPlanRepository(db)
        await repo.upsert(TestPlan(id="p1", project_id="p", task_id="T1"))
        await repo.upsert(TestPlan(id="p2", project_id="p", task_id="T2"))
        await repo.upsert(TestPlan(id="p3", project_id="q", task_id="T3"))
        listed = await repo.list_for_project("p")
        assert len(listed) == 2


class TestFlakeRepoIntegration:
    async def test_upsert_accumulates(self, db):
        repo = SQLiteFlakeRecordRepository(db)
        await repo.upsert(FlakeRecord(
            id="f1", project_id="p", test_id="tests/e2e/login::test_login",
            runs=5, failures=1,
        ))
        await repo.upsert(FlakeRecord(
            id="f1", project_id="p", test_id="tests/e2e/login::test_login",
            runs=10, failures=3, last_failure_reason="timeout",
        ))
        got = await repo.get_for_test("p", "tests/e2e/login::test_login")
        assert got is not None
        assert got.runs == 10
        assert got.failures == 3
        assert got.last_failure_reason == "timeout"

    async def test_list_for_project(self, db):
        repo = SQLiteFlakeRecordRepository(db)
        await repo.upsert(FlakeRecord(id="a", project_id="p", test_id="t1"))
        await repo.upsert(FlakeRecord(id="b", project_id="p", test_id="t2"))
        await repo.upsert(FlakeRecord(id="c", project_id="q", test_id="t3"))
        listed = await repo.list_for_project("p")
        assert len(listed) == 2


class TestQuarantineRepoIntegration:
    async def test_add_and_release(self, db):
        repo = SQLiteQuarantineRepository(db)
        entry = QuarantineEntry(
            id="q1", project_id="p", test_id="tests/e2e::flaky",
            reason="flake_score=0.4",
        )
        await repo.add(entry)

        active = await repo.list_active("p")
        assert len(active) == 1
        assert active[0].status == QuarantineStatus.ACTIVE

        await repo.release("q1", reason="fixed upstream")

        active_after = await repo.list_active("p")
        assert len(active_after) == 0

        all_for_project = await repo.list_for_project("p")
        assert len(all_for_project) == 1
        assert all_for_project[0].status == QuarantineStatus.RELEASED
        assert all_for_project[0].released_reason == "fixed upstream"
        assert all_for_project[0].released_at is not None


class TestQualityGateRepoIntegration:
    async def test_latest_for_gate(self, db):
        repo = SQLiteQualityGateRepository(db)
        await repo.add(QualityGate(
            id="g1", project_id="p", gate=GateName.AXE,
            status=GateStatus.FAIL, finding_count=3,
        ))
        await repo.add(QualityGate(
            id="g2", project_id="p", gate=GateName.AXE,
            status=GateStatus.PASS, finding_count=0,
        ))
        await repo.add(QualityGate(
            id="g3", project_id="p", gate=GateName.LIGHTHOUSE,
            status=GateStatus.WARN, score=78.0,
        ))

        latest_axe = await repo.latest_for_gate("p", GateName.AXE)
        assert latest_axe is not None
        assert latest_axe.status == GateStatus.PASS

        latest_lh = await repo.latest_for_gate("p", GateName.LIGHTHOUSE)
        assert latest_lh is not None
        assert latest_lh.score == 78.0

    async def test_list_for_project(self, db):
        repo = SQLiteQualityGateRepository(db)
        await repo.add(QualityGate(id="g1", project_id="p", gate=GateName.K6))
        await repo.add(QualityGate(id="g2", project_id="p", gate=GateName.OSV))
        await repo.add(QualityGate(id="g3", project_id="q", gate=GateName.SBOM))
        listed = await repo.list_for_project("p")
        assert len(listed) == 2


class TestOutcomeCardRepoIntegration:
    async def test_round_trip_acceptance(self, db):
        repo = SQLiteOutcomeCardRepository(db)
        card = OutcomeCard(
            id="c1",
            project_id="p",
            story_id="US-42",
            title="Login flow",
            acceptance=(
                StoryAcceptance(text="loads", passed=True, evidence="shot1.png"),
                StoryAcceptance(text="auth", passed=True),
                StoryAcceptance(text="rate limit", passed=False),
            ),
            metric_name="TTI",
            metric_before="3.2s",
            metric_after="1.8s",
        )
        await repo.add(card)

        got = await repo.get("c1")
        assert got is not None
        assert got.pass_count == 2
        assert got.fail_count == 1
        assert got.acceptance[0].evidence == "shot1.png"
        assert got.metric_after == "1.8s"

    async def test_list_for_project(self, db):
        repo = SQLiteOutcomeCardRepository(db)
        await repo.add(OutcomeCard(id="a", project_id="p"))
        await repo.add(OutcomeCard(id="b", project_id="p"))
        await repo.add(OutcomeCard(id="c", project_id="q"))
        listed = await repo.list_for_project("p")
        assert len(listed) == 2
