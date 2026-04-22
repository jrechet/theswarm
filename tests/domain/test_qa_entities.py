"""Domain tests for Phase F (QA enrichments) entities."""

from __future__ import annotations

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


class TestTestPlan:
    def test_missing_excludes_produced(self):
        plan = TestPlan(
            id="p",
            project_id="proj",
            task_id="T1",
            required=(TestArchetype.UNIT, TestArchetype.E2E, TestArchetype.A11Y),
            produced=(TestArchetype.UNIT,),
        )
        assert set(plan.missing) == {TestArchetype.E2E, TestArchetype.A11Y}
        assert plan.satisfied is False

    def test_fully_satisfied(self):
        plan = TestPlan(
            id="p",
            project_id="proj",
            task_id="T1",
            required=(TestArchetype.UNIT,),
            produced=(TestArchetype.UNIT,),
        )
        assert plan.satisfied is True
        assert plan.coverage_ratio == 1.0

    def test_no_requirements_is_trivially_satisfied(self):
        plan = TestPlan(id="p", project_id="proj", task_id="T1")
        assert plan.satisfied is True
        assert plan.coverage_ratio == 1.0

    def test_coverage_ratio_fractional(self):
        plan = TestPlan(
            id="p",
            project_id="proj",
            task_id="T1",
            required=(TestArchetype.UNIT, TestArchetype.E2E, TestArchetype.A11Y),
            produced=(TestArchetype.UNIT, TestArchetype.E2E),
        )
        assert plan.coverage_ratio == round(2 / 3, 3)


class TestFlakeRecord:
    def test_score_zero_when_no_runs(self):
        r = FlakeRecord(id="r", project_id="p", test_id="t")
        assert r.flake_score == 0.0

    def test_score_ratio(self):
        r = FlakeRecord(id="r", project_id="p", test_id="t", runs=10, failures=3)
        assert r.flake_score == 0.3

    def test_score_clamped_at_one(self):
        r = FlakeRecord(id="r", project_id="p", test_id="t", runs=5, failures=9)
        assert r.flake_score == 1.0

    def test_should_quarantine_requires_min_runs(self):
        r = FlakeRecord(id="r", project_id="p", test_id="t", runs=3, failures=2)
        # 66% flaky, but under min_runs=5 → not quarantined
        assert r.should_quarantine() is False

    def test_should_quarantine_above_threshold(self):
        r = FlakeRecord(id="r", project_id="p", test_id="t", runs=10, failures=3)
        assert r.should_quarantine(threshold=0.2) is True

    def test_should_quarantine_under_threshold(self):
        r = FlakeRecord(id="r", project_id="p", test_id="t", runs=20, failures=1)
        assert r.should_quarantine() is False


class TestQuarantineEntry:
    def test_defaults_active(self):
        q = QuarantineEntry(
            id="q",
            project_id="p",
            test_id="t",
            reason="flaky",
        )
        assert q.status == QuarantineStatus.ACTIVE
        assert q.released_at is None


class TestQualityGate:
    def test_fail_is_blocking(self):
        g = QualityGate(
            id="g",
            project_id="p",
            gate=GateName.AXE,
            status=GateStatus.FAIL,
        )
        assert g.is_blocking is True

    def test_warn_not_blocking(self):
        g = QualityGate(
            id="g",
            project_id="p",
            gate=GateName.LIGHTHOUSE,
            status=GateStatus.WARN,
        )
        assert g.is_blocking is False

    def test_pass_not_blocking(self):
        g = QualityGate(
            id="g", project_id="p", gate=GateName.K6, status=GateStatus.PASS,
        )
        assert g.is_blocking is False

    def test_new_id_prefix(self):
        assert QualityGate.new_id().startswith("gate_")


class TestOutcomeCard:
    def test_pass_fail_counts(self):
        card = OutcomeCard(
            id="c",
            project_id="p",
            acceptance=(
                StoryAcceptance(text="loads", passed=True),
                StoryAcceptance(text="accepts credentials", passed=True),
                StoryAcceptance(text="rate-limits", passed=False),
            ),
        )
        assert card.pass_count == 2
        assert card.fail_count == 1
        assert card.all_passed is False

    def test_all_passed_requires_non_empty(self):
        empty = OutcomeCard(id="c", project_id="p")
        assert empty.all_passed is False

    def test_all_passed_true(self):
        card = OutcomeCard(
            id="c",
            project_id="p",
            acceptance=(
                StoryAcceptance(text="one", passed=True),
                StoryAcceptance(text="two", passed=True),
            ),
        )
        assert card.all_passed is True


class TestValueObjects:
    def test_archetype_enum_values(self):
        assert TestArchetype.UNIT.value == "unit"
        assert TestArchetype.A11Y.value == "a11y"
        assert TestArchetype.PERF.value == "perf"

    def test_gate_name_enum(self):
        assert GateName.GITLEAKS.value == "gitleaks"
        assert GateName.SBOM.value == "sbom"

    def test_gate_status_enum(self):
        assert GateStatus.PASS.value == "pass"
        assert GateStatus.SKIPPED.value == "skipped"

    def test_quarantine_status(self):
        assert QuarantineStatus.ACTIVE.value == "active"
        assert QuarantineStatus.RELEASED.value == "released"


class TestIds:
    def test_id_prefixes(self):
        assert TestPlan.new_id().startswith("plan_")
        assert FlakeRecord.new_id().startswith("flake_")
        assert QuarantineEntry.new_id().startswith("quar_")
        assert OutcomeCard.new_id().startswith("card_")
