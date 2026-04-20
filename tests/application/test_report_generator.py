"""Tests for ReportGenerator service."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.application.services.report_generator import ReportGenerator
from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import (
    Budget,
    CycleId,
    CycleStatus,
    PhaseStatus,
)
from theswarm.domain.reporting.value_objects import QualityStatus


@pytest.fixture
def generator():
    return ReportGenerator()


def _make_cycle(
    status: CycleStatus = CycleStatus.COMPLETED,
    prs_opened: tuple[int, ...] = (),
    prs_merged: tuple[int, ...] = (),
    phases: tuple[PhaseExecution, ...] = (),
    cost: float = 1.5,
) -> Cycle:
    return Cycle(
        id=CycleId("cycle-1"),
        project_id="proj-1",
        status=status,
        triggered_by="test",
        started_at=datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 12, 10, 0, tzinfo=timezone.utc),
        total_cost_usd=cost,
        prs_opened=prs_opened,
        prs_merged=prs_merged,
        phases=phases,
    )


class TestGenerate:
    def test_generates_report_id(self, generator):
        cycle = _make_cycle()
        report = generator.generate(cycle)
        assert report.id.startswith("rpt-")
        assert len(report.id) > 4

    def test_maps_cycle_id(self, generator):
        cycle = _make_cycle()
        report = generator.generate(cycle)
        assert str(report.cycle_id) == "cycle-1"
        assert report.project_id == "proj-1"

    def test_summary_from_prs(self, generator):
        cycle = _make_cycle(prs_opened=(1, 2, 3), prs_merged=(1, 2))
        report = generator.generate(cycle)
        assert report.summary.prs_merged == 2
        assert report.summary.stories_completed == 2
        assert report.summary.stories_total == 3

    def test_summary_cost(self, generator):
        cycle = _make_cycle(cost=7.5)
        report = generator.generate(cycle)
        assert report.summary.cost_usd == 7.5

    def test_thumbnail_rel_path_attaches_artifact(self, generator):
        """F4 — thumbnail_rel_path makes `DemoReport.thumbnail_path` resolvable."""
        cycle = _make_cycle()
        report = generator.generate(cycle, thumbnail_rel_path="cyc/thumbnail/cover.jpg")
        assert report.thumbnail_path == "cyc/thumbnail/cover.jpg"
        assert len(report.artifacts) == 1
        assert report.artifacts[0].mime_type == "image/jpeg"
        assert report.artifacts[0].path == "cyc/thumbnail/cover.jpg"

    def test_thumbnail_rel_path_empty_string_leaves_artifacts_empty(self, generator):
        cycle = _make_cycle()
        report = generator.generate(cycle)
        assert report.artifacts == ()
        assert report.thumbnail_path is None

    def test_completed_cycle_gate_passes(self, generator):
        cycle = _make_cycle(status=CycleStatus.COMPLETED)
        report = generator.generate(cycle)
        completion_gate = next(
            g for g in report.quality_gates if g.name == "cycle_completion"
        )
        assert completion_gate.status == QualityStatus.PASS

    def test_failed_cycle_gate_fails(self, generator):
        cycle = _make_cycle(status=CycleStatus.FAILED)
        report = generator.generate(cycle)
        completion_gate = next(
            g for g in report.quality_gates if g.name == "cycle_completion"
        )
        assert completion_gate.status == QualityStatus.FAIL

    def test_running_cycle_gate_warns(self, generator):
        cycle = _make_cycle(status=CycleStatus.RUNNING)
        report = generator.generate(cycle)
        completion_gate = next(
            g for g in report.quality_gates if g.name == "cycle_completion"
        )
        assert completion_gate.status == QualityStatus.WARN

    def test_failed_phase_adds_gate(self, generator):
        phases = (
            PhaseExecution(phase="morning", agent="po", started_at=datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc), status=PhaseStatus.COMPLETED),
            PhaseExecution(phase="dev", agent="dev", started_at=datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc), status=PhaseStatus.FAILED),
        )
        cycle = _make_cycle(phases=phases)
        report = generator.generate(cycle)
        phase_gates = [g for g in report.quality_gates if g.name.startswith("phase_")]
        assert len(phase_gates) == 1
        assert phase_gates[0].name == "phase_dev"
        assert phase_gates[0].status == QualityStatus.FAIL

    def test_all_phases_pass_no_phase_gates(self, generator):
        phases = (
            PhaseExecution(phase="morning", agent="po", started_at=datetime(2026, 4, 12, 8, 0, tzinfo=timezone.utc), status=PhaseStatus.COMPLETED),
            PhaseExecution(phase="dev", agent="dev", started_at=datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc), status=PhaseStatus.COMPLETED),
        )
        cycle = _make_cycle(phases=phases)
        report = generator.generate(cycle)
        phase_gates = [g for g in report.quality_gates if g.name.startswith("phase_")]
        assert len(phase_gates) == 0
