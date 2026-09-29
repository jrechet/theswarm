"""Service to generate DemoReports from cycle data."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleStatus, PhaseStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
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
        qa_gates: dict | None = None,
        videos: tuple[dict, ...] | list[dict] = (),
        stories: tuple[StoryReport, ...] | list[StoryReport] = (),
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

        ``videos``: QA's `demo_report["videos"]` (each ``type``/``label``/
        ``path``/``size_bytes``), attached as VIDEO artifacts after the
        thumbnail and the screenshots — the repo card and the player read
        the first one. No report carried one before 2026-09-27: the video
        was recorded every cycle and never shown.

        ``qa_gates``: QA's `demo_report["quality_gates"]` (unit, E2E,
        security, coverage). The report is the one record of a cycle that
        outlives the container; without these it said only "the cycle
        completed" (1418b48f3180, 2026-09-26: coverage 96.8%, an E2E failure).
        """
        summary = self._build_summary(cycle, held_prs, qa_gates)
        gates = self._build_quality_gates(cycle) + _qa_quality_gates(qa_gates)

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

        for video in videos:
            path = video.get("path", "") if isinstance(video, dict) else ""
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            artifacts.append(Artifact(
                type=ArtifactType.VIDEO,
                label=video.get("label", "demo_recording"),
                path=path,
                mime_type=video.get("mime_type") or "video/webm",
                size_bytes=video.get("size_bytes", 0),
            ))

        return DemoReport(
            id=f"rpt-{uuid.uuid4().hex[:8]}",
            stories=tuple(stories),
            cycle_id=cycle.id,
            project_id=cycle.project_id,
            created_at=datetime.now(timezone.utc),
            summary=summary,
            quality_gates=gates,
            artifacts=tuple(artifacts),
            agent_learnings=tuple(agent_learnings),
        )

    def _build_summary(
        self, cycle: Cycle, held_prs: tuple[int, ...] = (), qa_gates: dict | None = None,
    ) -> ReportSummary:
        prs_merged = len(cycle.prs_merged)
        prs_opened = len(cycle.prs_opened)
        passing, total, coverage, high = _qa_numbers(qa_gates)

        return ReportSummary(
            stories_completed=prs_merged,
            stories_total=prs_opened or prs_merged,
            prs_merged=prs_merged,
            prs_held=len(held_prs),
            tests_passing=passing,
            tests_total=total,
            coverage_percent=coverage,
            security_critical=high,
            cost_usd=cycle.total_cost_usd,
        )

    @staticmethod
    def stories_of(demo: dict) -> tuple[StoryReport, ...]:
        """The cycle's stories from QA's report: one per delivered task
        (`user_stories`), with the walk's captures of its feature pages
        (`story_screenshots`) and its walkthrough (`story_videos`).

        No stored report carried a story before 2026-09-27: the player's
        per-story slides and the card's per-story captures read an empty
        tuple every time.
        """
        if not isinstance(demo, dict):
            return ()
        shots = demo.get("story_screenshots") or {}
        videos = demo.get("story_videos") or {}
        stories: list[StoryReport] = []
        for entry in demo.get("user_stories") or []:
            if not isinstance(entry, dict):
                continue
            pr = entry.get("pr")
            bucket = _by_pr(shots, pr) or {}
            video = _by_pr(videos, pr)
            ticket = str(entry.get("task") or pr or "?")
            status = str(entry.get("status", ""))
            stories.append(StoryReport(
                ticket_id=ticket,
                # A task found already on main comes without a title: the
                # player showed an empty heading for #383 (2026-09-28).
                title=entry.get("title") or f"#{ticket} — {status or 'delivered'}",
                status=_STORY_STATUS.get(str(entry.get("status", "")), "in_progress"),
                pr_number=pr if isinstance(pr, int) else None,
                pr_url=entry.get("url") or "",
                screenshots_before=_shot_artifacts(bucket.get("before") or []),
                screenshots_after=_shot_artifacts(bucket.get("after") or []),
                video=_video_artifact(video) if isinstance(video, dict) else None,
            ))
        return tuple(stories)

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


_QA_STATUS = {
    "pass": QualityStatus.PASS,
    "fail": QualityStatus.FAIL,
    "warn": QualityStatus.WARN,
    "not_run": QualityStatus.SKIP,
    "inconclusive": QualityStatus.WARN,  # the feature's tests were wrong, not the app
}


def _qa_numbers(qa_gates: dict | None) -> tuple[int, int, float, int]:
    """(tests passing, tests total, coverage %, HIGH findings) from QA's
    gates — unit and E2E together; a gate that did not run counts nothing.
    The summary was built from the cycle alone and read "0/0 tests, 0.0 %"
    one slide before the gates said 361 passed at 97.1 % (28371c2016da)."""
    gates = qa_gates or {}
    passing = total = 0
    for name in ("unit_tests", "e2e_tests"):
        gate = gates.get(name)
        if isinstance(gate, dict) and gate.get("status") in ("pass", "fail"):
            passing += int(gate.get("passed") or 0)
            total += int(gate.get("total") or 0)
    coverage_gate = gates.get("coverage")
    coverage = (
        float(coverage_gate.get("percent") or 0.0)
        if isinstance(coverage_gate, dict) and coverage_gate.get("status") in ("pass", "fail")
        else 0.0
    )
    security = gates.get("security")
    high = int(security.get("semgrep_high") or 0) if isinstance(security, dict) else 0
    return passing, total, coverage, high


def _qa_quality_gates(qa_gates: dict | None) -> tuple[QualityGate, ...]:
    """QA's gates as report gates, in QA's order; odd entries are skipped."""
    gates = []
    for name, gate in (qa_gates or {}).items():
        if not isinstance(gate, dict):
            continue
        status = _QA_STATUS.get(str(gate.get("status", "")), QualityStatus.WARN)
        value = gate.get("percent") if name == "coverage" else None
        gates.append(QualityGate(
            name=name, status=status, detail=_qa_gate_detail(name, gate, status),
            value=float(value) if isinstance(value, (int, float)) else None,
        ))
    return tuple(gates)


def _qa_gate_detail(name: str, gate: dict, status: QualityStatus) -> str:
    if status == QualityStatus.SKIP:
        reason = gate.get("reason") or ""
        return f"not run: {reason}" if reason else "not run"
    if name == "security":
        return f"{gate.get('semgrep_high', 0)} HIGH findings"
    if name == "coverage":
        return f"{gate.get('percent', 0)}% (threshold {gate.get('threshold', 70)}%)"
    if "passed" not in gate:
        return str(gate.get("reason") or "")
    detail = f"{gate.get('passed', 0)} passed, {gate.get('failed', 0)} failed"
    if gate.get("status") == "inconclusive" and gate.get("reason"):
        detail += " — " + str(gate["reason"])  # who was wrong, before what pytest said
    elif gate.get("failure_excerpt"):
        detail += " — " + str(gate["failure_excerpt"])
    elif gate.get("reason"):  # the feature's tests: which failed, and who is wrong
        detail += " — " + str(gate["reason"])
    if gate.get("repaired_from"):
        detail += f" (file repaired once: {_first_error(str(gate['repaired_from']))})"
    return detail


_DETAIL_LINE_LIMIT = 160


def _first_error(excerpt: str) -> str:
    """pytest's excerpt said in one line: its first `E` line, else its first
    line that is not a `___ header ___`. A passing gate carried a dozen
    "ERROR at setup of …" blocks onto the gates slide (cancel-tour)."""
    lines = [line.strip() for line in excerpt.splitlines() if line.strip()]
    errors = [line[1:].strip() for line in lines if line.startswith("E ")]
    plain = [line for line in lines if not line.startswith("_")]
    first = (errors or plain or [excerpt.strip()])[0]
    return first[:_DETAIL_LINE_LIMIT]


# What a delivered task's status reads as on the report.
_STORY_STATUS = {"merged": "completed", "already on main": "completed", "open": "in_progress"}


def _by_pr(mapping: dict, pr) -> dict | None:
    """A per-PR entry, whether the key survived as an int or a string."""
    if pr is None or not isinstance(mapping, dict):
        return None
    value = mapping.get(pr, mapping.get(str(pr)))
    return value if isinstance(value, dict) else None


def _shot_artifacts(entries: list) -> tuple[Artifact, ...]:
    return tuple(
        Artifact(type=ArtifactType.SCREENSHOT, label=e.get("label", "screenshot"), path=e["path"],
                 mime_type="image/png", size_bytes=e.get("size_bytes", 0))
        for e in entries if isinstance(e, dict) and e.get("path")
    )


def _video_artifact(entry: dict) -> Artifact | None:
    if not entry.get("path"):
        return None
    return Artifact(type=ArtifactType.VIDEO, label=entry.get("label", "walkthrough"), path=entry["path"],
                    mime_type=entry.get("mime_type") or "video/webm", size_bytes=entry.get("size_bytes", 0))
