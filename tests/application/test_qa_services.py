"""Phase F application-layer tests for QA-enrichments services."""

from __future__ import annotations

import pytest

from theswarm.application.services.qa import (
    ArchetypeMixService,
    FlakeTrackerService,
    OutcomeCardService,
    QualityGateService,
    QuarantineService,
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
    conn = await init_db(str(tmp_path / "qa_services.db"))
    yield conn
    await conn.close()


class TestArchetypeMixService:
    async def test_set_required_then_mark_produced(self, db):
        svc = ArchetypeMixService(SQLiteTestPlanRepository(db))
        plan = await svc.set_required(
            project_id="p", task_id="T1",
            required=(TestArchetype.UNIT, TestArchetype.E2E, TestArchetype.A11Y),
        )
        assert plan.coverage_ratio == 0.0
        assert set(plan.missing) == {
            TestArchetype.UNIT, TestArchetype.E2E, TestArchetype.A11Y,
        }

        await svc.mark_produced(
            project_id="p", task_id="T1", archetype=TestArchetype.UNIT,
        )
        plan2 = await svc.mark_produced(
            project_id="p", task_id="T1", archetype=TestArchetype.E2E,
        )
        assert plan2 is not None
        assert set(plan2.produced) == {TestArchetype.UNIT, TestArchetype.E2E}
        assert plan2.satisfied is False

    async def test_mark_produced_is_idempotent(self, db):
        svc = ArchetypeMixService(SQLiteTestPlanRepository(db))
        await svc.set_required(
            project_id="p", task_id="T1", required=(TestArchetype.UNIT,),
        )
        await svc.mark_produced(
            project_id="p", task_id="T1", archetype=TestArchetype.UNIT,
        )
        plan = await svc.mark_produced(
            project_id="p", task_id="T1", archetype=TestArchetype.UNIT,
        )
        assert plan is not None
        assert plan.produced == (TestArchetype.UNIT,)

    async def test_mark_produced_without_plan_returns_none(self, db):
        svc = ArchetypeMixService(SQLiteTestPlanRepository(db))
        result = await svc.mark_produced(
            project_id="p", task_id="T404", archetype=TestArchetype.UNIT,
        )
        assert result is None


class TestFlakeTrackerService:
    async def test_record_run_first_pass(self, db):
        svc = FlakeTrackerService(SQLiteFlakeRecordRepository(db))
        record = await svc.record_run(
            project_id="p", test_id="tests/x::y", failed=False,
        )
        assert record.runs == 1
        assert record.failures == 0
        assert record.flake_score == 0.0

    async def test_record_run_first_failure(self, db):
        svc = FlakeTrackerService(SQLiteFlakeRecordRepository(db))
        record = await svc.record_run(
            project_id="p", test_id="tests/x::y", failed=True,
            failure_reason="assertion",
        )
        assert record.failures == 1
        assert record.last_failure_reason == "assertion"

    async def test_accumulates_across_runs(self, db):
        svc = FlakeTrackerService(SQLiteFlakeRecordRepository(db))
        for failed in [True, False, True, False, False, True, False, False, False, False]:
            await svc.record_run(
                project_id="p", test_id="tests/x::y", failed=failed,
            )
        rec = await svc.get("p", "tests/x::y")
        assert rec is not None
        assert rec.runs == 10
        assert rec.failures == 3
        assert rec.flake_score == 0.3
        assert rec.should_quarantine(threshold=0.2) is True


class TestQuarantineService:
    async def test_quarantine_and_release(self, db):
        svc = QuarantineService(SQLiteQuarantineRepository(db))
        entry = await svc.quarantine(
            project_id="p", test_id="tests/x::y", reason="flaky",
        )
        active = await svc.list_active("p")
        assert len(active) == 1
        assert active[0].status == QuarantineStatus.ACTIVE

        await svc.release(entry_id=entry.id, reason="fixed")
        active_after = await svc.list_active("p")
        assert len(active_after) == 0

        all_entries = await svc.list_all("p")
        assert len(all_entries) == 1
        assert all_entries[0].released_reason == "fixed"


class TestQualityGateService:
    async def test_latest_snapshot(self, db):
        svc = QualityGateService(SQLiteQualityGateRepository(db))
        await svc.record(
            project_id="p", gate=GateName.AXE, status=GateStatus.FAIL,
            finding_count=4,
        )
        await svc.record(
            project_id="p", gate=GateName.AXE, status=GateStatus.PASS,
        )
        await svc.record(
            project_id="p", gate=GateName.LIGHTHOUSE, status=GateStatus.WARN,
            score=76.5,
        )

        snapshot = await svc.latest_snapshot("p")
        assert GateName.AXE in snapshot
        assert snapshot[GateName.AXE].status == GateStatus.PASS
        assert snapshot[GateName.LIGHTHOUSE].score == 76.5
        assert GateName.SBOM not in snapshot  # never recorded

    async def test_list(self, db):
        svc = QualityGateService(SQLiteQualityGateRepository(db))
        await svc.record(project_id="p", gate=GateName.K6)
        await svc.record(project_id="p", gate=GateName.OSV)
        listed = await svc.list("p")
        assert len(listed) == 2


class TestOutcomeCardService:
    async def test_create_with_acceptance(self, db):
        svc = OutcomeCardService(SQLiteOutcomeCardRepository(db))
        card = await svc.create(
            project_id="p", story_id="US-1", title="Login",
            acceptance=(
                svc.make_acceptance(text="loads", passed=True),
                svc.make_acceptance(text="locked-out", passed=False),
            ),
            metric_name="TTI",
            metric_before="3s", metric_after="1.5s",
        )
        assert card.pass_count == 1
        assert card.fail_count == 1
        assert card.all_passed is False

        fetched = await svc.get(card.id)
        assert fetched is not None
        assert fetched.metric_before == "3s"

    async def test_list_newest_first(self, db):
        svc = OutcomeCardService(SQLiteOutcomeCardRepository(db))
        await svc.create(project_id="p", title="first")
        await svc.create(project_id="p", title="second")
        listed = await svc.list("p")
        assert len(listed) == 2
        assert listed[0].title == "second"
