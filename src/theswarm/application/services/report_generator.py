"""Service to generate DemoReports from cycle data."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleStatus, PhaseStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus


class ReportGenerator:
    """Builds a DemoReport from a completed Cycle.

    In a full integration, this would also pull data from:
    - GitHub PRs (files changed, lines, screenshots)
    - Test runner results (coverage, pass/fail counts)
    - Security scanner results

    For now, it produces a report from what's available in the Cycle entity.
    """

    def generate(self, cycle: Cycle) -> DemoReport:
        """Create a report from a cycle."""
        summary = self._build_summary(cycle)
        gates = self._build_quality_gates(cycle)

        return DemoReport(
            id=f"rpt-{uuid.uuid4().hex[:8]}",
            cycle_id=cycle.id,
            project_id=cycle.project_id,
            created_at=datetime.now(timezone.utc),
            summary=summary,
            quality_gates=gates,
        )

    def _build_summary(self, cycle: Cycle) -> ReportSummary:
        prs_merged = len(cycle.prs_merged)
        prs_opened = len(cycle.prs_opened)

        return ReportSummary(
            stories_completed=prs_merged,
            stories_total=prs_opened or prs_merged,
            prs_merged=prs_merged,
            cost_usd=cycle.total_cost_usd,
        )

    def _build_quality_gates(self, cycle: Cycle) -> tuple[QualityGate, ...]:
        gates = []

        # Cycle completion gate
        if cycle.status == CycleStatus.COMPLETED:
            gates.append(QualityGate(
                name="cycle_completion",
                status=QualityStatus.PASS,
                detail="Cycle completed successfully",
            ))
        elif cycle.status == CycleStatus.FAILED:
            gates.append(QualityGate(
                name="cycle_completion",
                status=QualityStatus.FAIL,
                detail="Cycle failed",
            ))
        else:
            gates.append(QualityGate(
                name="cycle_completion",
                status=QualityStatus.WARN,
                detail=f"Cycle status: {cycle.status.value}",
            ))

        # Phase completion gates
        for phase in cycle.phases:
            if phase.status == PhaseStatus.FAILED:
                gates.append(QualityGate(
                    name=f"phase_{phase.phase}",
                    status=QualityStatus.FAIL,
                    detail=f"Phase {phase.phase} failed",
                ))

        return tuple(gates)
