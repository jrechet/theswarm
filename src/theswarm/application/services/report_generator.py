"""Service to generate DemoReports from cycle data."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleStatus, PhaseStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.value_objects import (
    Artifact,
    ArtifactType,
    QualityGate,
    QualityStatus,
)


class ReportGenerator:
    """Builds a DemoReport from a completed Cycle.

    In a full integration, this would also pull data from:
    - GitHub PRs (files changed, lines, screenshots)
    - Test runner results (coverage, pass/fail counts)
    - Security scanner results

    For now, it produces a report from what's available in the Cycle entity.
    """

    def generate(
        self,
        cycle: Cycle,
        thumbnail_rel_path: str = "",
        agent_learnings: tuple[str, ...] = (),
        screenshots: tuple[dict, ...] | list[dict] = (),
        held_prs: tuple[int, ...] = (),
    ) -> DemoReport:
        """Create a report from a cycle.

        ``thumbnail_rel_path`` (F4): optional relative artifact path for the
        cover thumbnail. When provided, it is attached to the report as a
        SCREENSHOT artifact first, so ``DemoReport.thumbnail_path`` (which
        resolves to the first screenshot) resolves to it rather than to one
        of ``screenshots``.

        ``screenshots``: the QA-captured demo screenshots (``demo_report
        ["screenshots"]`` — each a dict with ``type``/``label``/``path``),
        attached next to the thumbnail so the card's gallery and count are
        not just the one cover image. A screenshot whose path matches the
        thumbnail is not duplicated.

        ``held_prs``: PRs TechLead approved but left for a human to merge
        (SELF_REPO) — reported separately from ``prs_merged``.
        """
        summary = self._build_summary(cycle, held_prs)
        gates = self._build_quality_gates(cycle)

        artifacts: list[Artifact] = []
        seen_paths: set[str] = set()

        if thumbnail_rel_path:
            mime = "image/jpeg" if thumbnail_rel_path.endswith((".jpg", ".jpeg")) else "image/png"
            artifacts.append(Artifact(
                type=ArtifactType.SCREENSHOT,
                label="demo_thumbnail",
                path=thumbnail_rel_path,
                mime_type=mime,
            ))
            seen_paths.add(thumbnail_rel_path)

        for shot in screenshots:
            path = shot.get("path", "") if isinstance(shot, dict) else ""
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            mime = shot.get("mime_type") or (
                "image/jpeg" if path.endswith((".jpg", ".jpeg")) else "image/png"
            )
            artifacts.append(Artifact(
                type=ArtifactType.SCREENSHOT,
                label=shot.get("label", "screenshot"),
                path=path,
                mime_type=mime,
                size_bytes=shot.get("size_bytes", 0),
            ))

        return DemoReport(
            id=f"rpt-{uuid.uuid4().hex[:8]}",
            cycle_id=cycle.id,
            project_id=cycle.project_id,
            created_at=datetime.now(timezone.utc),
            summary=summary,
            quality_gates=gates,
            artifacts=tuple(artifacts),
            agent_learnings=tuple(agent_learnings),
        )

    def _build_summary(self, cycle: Cycle, held_prs: tuple[int, ...] = ()) -> ReportSummary:
        prs_merged = len(cycle.prs_merged)
        prs_opened = len(cycle.prs_opened)

        return ReportSummary(
            stories_completed=prs_merged,
            stories_total=prs_opened or prs_merged,
            prs_merged=prs_merged,
            prs_held=len(held_prs),
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
