"""Tests for ImprovementEngine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.application.services.improvement_engine import (
    ImprovementEngine,
    ImprovementSuggestion,
)
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.memory.value_objects import MemoryCategory
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus


@pytest.fixture
def engine():
    return ImprovementEngine()


def _make_report(
    summary: ReportSummary | None = None,
    quality_gates: tuple[QualityGate, ...] = (),
) -> DemoReport:
    return DemoReport(
        id="rpt-1",
        cycle_id=CycleId("cycle-1"),
        project_id="proj-1",
        created_at=datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc),
        summary=summary or ReportSummary(),
        quality_gates=quality_gates,
    )


class TestQualityGateAnalysis:
    def test_failed_gate_high_priority(self, engine):
        report = _make_report(quality_gates=(
            QualityGate(name="tests", status=QualityStatus.FAIL, detail="3 failing"),
        ))
        suggestions = engine.analyze_report(report)
        assert len(suggestions) >= 1
        s = suggestions[0]
        assert s.priority == 1
        assert "tests" in s.description
        assert s.source == "quality_gate"

    def test_warn_gate_medium_priority(self, engine):
        report = _make_report(quality_gates=(
            QualityGate(name="security", status=QualityStatus.WARN, detail="1 medium"),
        ))
        suggestions = engine.analyze_report(report)
        assert any(s.priority == 2 and "security" in s.description for s in suggestions)

    def test_pass_gate_no_suggestion(self, engine):
        report = _make_report(quality_gates=(
            QualityGate(name="tests", status=QualityStatus.PASS),
        ))
        suggestions = engine.analyze_report(report)
        assert not any(s.source == "quality_gate" for s in suggestions)

    def test_skip_gate_no_suggestion(self, engine):
        report = _make_report(quality_gates=(
            QualityGate(name="lint", status=QualityStatus.SKIP),
        ))
        suggestions = engine.analyze_report(report)
        assert not any(s.source == "quality_gate" for s in suggestions)


class TestCoverageAnalysis:
    def test_low_coverage_high_priority(self, engine):
        report = _make_report(summary=ReportSummary(coverage_percent=50.0))
        suggestions = engine.analyze_report(report)
        cov_suggestions = [s for s in suggestions if s.source == "coverage"]
        assert len(cov_suggestions) == 1
        assert cov_suggestions[0].priority == 1
        assert "50.0%" in cov_suggestions[0].description

    def test_medium_coverage_low_priority(self, engine):
        report = _make_report(summary=ReportSummary(coverage_percent=75.0))
        suggestions = engine.analyze_report(report)
        cov_suggestions = [s for s in suggestions if s.source == "coverage"]
        assert len(cov_suggestions) == 1
        assert cov_suggestions[0].priority == 3

    def test_good_coverage_no_suggestion(self, engine):
        report = _make_report(summary=ReportSummary(coverage_percent=90.0))
        suggestions = engine.analyze_report(report)
        assert not any(s.source == "coverage" for s in suggestions)

    def test_zero_coverage_no_suggestion(self, engine):
        report = _make_report(summary=ReportSummary(coverage_percent=0.0))
        suggestions = engine.analyze_report(report)
        assert not any(s.source == "coverage" for s in suggestions)


class TestCostAnalysis:
    def test_high_cost_warns(self, engine):
        report = _make_report(summary=ReportSummary(cost_usd=15.0))
        suggestions = engine.analyze_report(report)
        cost_suggestions = [s for s in suggestions if s.source == "cost"]
        assert len(cost_suggestions) == 1
        assert "$15.00" in cost_suggestions[0].description

    def test_normal_cost_no_suggestion(self, engine):
        report = _make_report(summary=ReportSummary(cost_usd=5.0))
        suggestions = engine.analyze_report(report)
        assert not any(s.source == "cost" for s in suggestions)


class TestCompletionRate:
    def test_low_completion_high_priority(self, engine):
        report = _make_report(summary=ReportSummary(stories_total=10, stories_completed=3))
        suggestions = engine.analyze_report(report)
        pattern_suggestions = [s for s in suggestions if s.source == "pattern"]
        assert len(pattern_suggestions) == 1
        assert pattern_suggestions[0].priority == 1

    def test_good_completion_no_suggestion(self, engine):
        report = _make_report(summary=ReportSummary(stories_total=5, stories_completed=4))
        suggestions = engine.analyze_report(report)
        assert not any(s.source == "pattern" for s in suggestions)

    def test_zero_total_no_suggestion(self, engine):
        report = _make_report(summary=ReportSummary(stories_total=0, stories_completed=0))
        suggestions = engine.analyze_report(report)
        assert not any(s.source == "pattern" for s in suggestions)


class TestGenerateRetrospective:
    def test_produces_retrospective(self, engine):
        report = _make_report(
            summary=ReportSummary(coverage_percent=50.0, cost_usd=20.0),
            quality_gates=(
                QualityGate(name="tests", status=QualityStatus.FAIL, detail="broken"),
            ),
        )
        suggestions = engine.analyze_report(report)
        retro = engine.generate_retrospective(report, suggestions)
        assert retro.project_id == "proj-1"
        assert retro.cycle_date == "2026-04-12"
        assert retro.count == len(suggestions)
        assert all(e.agent == "improver" for e in retro.entries)

    def test_empty_suggestions_empty_retro(self, engine):
        report = _make_report(summary=ReportSummary(coverage_percent=95.0))
        suggestions = engine.analyze_report(report)
        retro = engine.generate_retrospective(report, suggestions)
        assert retro.count == 0


class TestSortOrder:
    def test_sorted_by_priority(self, engine):
        report = _make_report(
            summary=ReportSummary(
                coverage_percent=50.0,
                cost_usd=15.0,
                stories_total=10,
                stories_completed=3,
            ),
            quality_gates=(
                QualityGate(name="lint", status=QualityStatus.WARN, detail="x"),
            ),
        )
        suggestions = engine.analyze_report(report)
        priorities = [s.priority for s in suggestions]
        assert priorities == sorted(priorities)
