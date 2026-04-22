"""Domain tests for Phase E (Dev rigour) entities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from theswarm.domain.dev_rigour.entities import (
    CoverageDelta,
    DevThought,
    RefactorPreflight,
    SelfReview,
    SelfReviewFinding,
    TddArtifact,
)
from theswarm.domain.dev_rigour.value_objects import (
    FindingSeverity,
    PreflightDecision,
    TddPhase,
    ThoughtKind,
)


class TestDevThought:
    def test_defaults(self):
        t = DevThought(id="thought_1", project_id="p")
        assert t.kind == ThoughtKind.NOTE
        assert t.content == ""
        assert t.task_id == ""

    def test_new_id_prefix(self):
        assert DevThought.new_id().startswith("thought_")


class TestTddArtifact:
    def test_red_phase_not_green(self):
        a = TddArtifact(id="a", project_id="p", task_id="t1")
        assert a.phase == TddPhase.RED
        assert a.is_green is False

    def test_green_is_green(self):
        a = TddArtifact(
            id="a", project_id="p", task_id="t1", phase=TddPhase.GREEN,
        )
        assert a.is_green is True

    def test_refactor_counts_as_green(self):
        a = TddArtifact(
            id="a", project_id="p", task_id="t1", phase=TddPhase.REFACTOR,
        )
        assert a.is_green is True

    def test_new_id_prefix(self):
        assert TddArtifact.new_id().startswith("tdd_")


class TestRefactorPreflight:
    def test_default_proceed(self):
        p = RefactorPreflight(id="r", project_id="p")
        assert p.decision == PreflightDecision.PROCEED
        assert p.deletion_lines == 0

    def test_bail_decision(self):
        p = RefactorPreflight(
            id="r",
            project_id="p",
            deletion_lines=42,
            decision=PreflightDecision.BAIL,
            reason="unclear callers",
        )
        assert p.decision == PreflightDecision.BAIL
        assert p.reason == "unclear callers"

    def test_files_and_callers_are_tuples(self):
        p = RefactorPreflight(
            id="r",
            project_id="p",
            files_touched=("a.py", "b.py"),
            callers_checked=("x.py",),
        )
        assert p.files_touched == ("a.py", "b.py")
        assert p.callers_checked == ("x.py",)


class TestSelfReview:
    def test_high_count_counts_high_and_critical(self):
        r = SelfReview(
            id="s",
            project_id="p",
            findings=(
                SelfReviewFinding(severity=FindingSeverity.LOW),
                SelfReviewFinding(severity=FindingSeverity.HIGH),
                SelfReviewFinding(severity=FindingSeverity.CRITICAL),
                SelfReviewFinding(severity=FindingSeverity.MEDIUM),
            ),
        )
        assert r.high_count == 2

    def test_waived_high_does_not_count(self):
        r = SelfReview(
            id="s",
            project_id="p",
            findings=(
                SelfReviewFinding(
                    severity=FindingSeverity.HIGH,
                    waived=True,
                    waive_reason="ship-it override",
                ),
                SelfReviewFinding(severity=FindingSeverity.HIGH),
            ),
        )
        assert r.high_count == 1
        assert r.waived_count == 1

    def test_empty_findings(self):
        r = SelfReview(id="s", project_id="p")
        assert r.high_count == 0
        assert r.waived_count == 0


class TestCoverageDelta:
    def test_delta_positive(self):
        cd = CoverageDelta(
            id="c",
            project_id="p",
            total_before_pct=75.0,
            total_after_pct=82.5,
            changed_lines_pct=90.0,
        )
        assert cd.delta == 7.5
        assert cd.passes_threshold is True

    def test_delta_negative(self):
        cd = CoverageDelta(
            id="c",
            project_id="p",
            total_before_pct=82.0,
            total_after_pct=79.0,
            changed_lines_pct=60.0,
            threshold_pct=80.0,
        )
        assert cd.delta == -3.0
        assert cd.passes_threshold is False

    def test_threshold_boundary_inclusive(self):
        cd = CoverageDelta(
            id="c",
            project_id="p",
            changed_lines_pct=80.0,
            threshold_pct=80.0,
        )
        assert cd.passes_threshold is True

    def test_new_id_prefix(self):
        assert CoverageDelta.new_id().startswith("covd_")


class TestTimestamps:
    def test_default_timestamps_are_utc(self):
        t = DevThought(id="x", project_id="p")
        assert t.created_at.tzinfo == timezone.utc

    def test_explicit_timestamps_preserved(self):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t = DevThought(id="x", project_id="p", created_at=ts)
        assert t.created_at == ts


class TestValueObjects:
    def test_thought_kinds(self):
        assert ThoughtKind.EXPLORE.value == "explore"
        assert ThoughtKind.REUSE.value == "reuse"
        assert ThoughtKind.LIBRARY.value == "library"

    def test_severity_enum(self):
        assert FindingSeverity.HIGH.value == "high"
        assert FindingSeverity.CRITICAL.value == "critical"

    def test_preflight_enum(self):
        assert PreflightDecision.BAIL.value == "bail"
        assert PreflightDecision.PROCEED.value == "proceed"

    def test_tdd_phase_enum(self):
        assert TddPhase.RED.value == "red"
        assert TddPhase.GREEN.value == "green"


class TestAgeAndDates:
    def test_coverage_delta_rounding(self):
        cd = CoverageDelta(
            id="c",
            project_id="p",
            total_before_pct=70.123,
            total_after_pct=72.456,
        )
        # delta rounded to 2 decimals
        assert cd.delta == 2.33

    def test_preflight_created_is_recent(self):
        p = RefactorPreflight(id="r", project_id="p")
        assert datetime.now(timezone.utc) - p.created_at < timedelta(seconds=2)
