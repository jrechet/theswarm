"""SQLite-backed report repository."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.value_objects import (
    Artifact,
    ArtifactType,
    DiffHighlight,
    QualityGate,
    QualityStatus,
)


class SQLiteReportRepository:
    """Implements ReportRepository using the reports table.

    Uses the schema: id, cycle_id, project_id, summary_json, stories_json,
    quality_json, learnings_json, artifacts_json, created_at.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def save(self, report: DemoReport) -> None:
        await self._conn.execute(
            """INSERT OR REPLACE INTO reports
               (id, cycle_id, project_id, summary_json, stories_json,
                quality_json, learnings_json, artifacts_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                str(report.cycle_id),
                report.project_id,
                _serialize_summary(report.summary),
                _serialize_stories(report.stories),
                _serialize_quality_gates(report.quality_gates),
                json.dumps(list(report.agent_learnings)),
                _serialize_artifacts(report.artifacts),
                report.created_at.isoformat(),
            ),
        )
        await self._conn.commit()

    async def get(self, report_id: str) -> DemoReport | None:
        cursor = await self._conn.execute(
            """SELECT id, cycle_id, project_id, summary_json, stories_json,
                      quality_json, learnings_json, artifacts_json, created_at
               FROM reports WHERE id = ?""",
            (report_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_report(row)

    async def list_by_project(self, project_id: str, limit: int = 30) -> list[DemoReport]:
        cursor = await self._conn.execute(
            """SELECT id, cycle_id, project_id, summary_json, stories_json,
                      quality_json, learnings_json, artifacts_json, created_at
               FROM reports WHERE project_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_report(r) for r in rows]

    async def list_by_cycle(self, cycle_id: str, limit: int = 10) -> list[DemoReport]:
        cursor = await self._conn.execute(
            """SELECT id, cycle_id, project_id, summary_json, stories_json,
                      quality_json, learnings_json, artifacts_json, created_at
               FROM reports WHERE cycle_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (cycle_id, limit),
        )
        rows = await cursor.fetchall()
        return [_row_to_report(r) for r in rows]


# ── Serialization ─────────────────────────────────────────────────


def _serialize_summary(s: ReportSummary) -> str:
    return json.dumps({
        "stories_completed": s.stories_completed,
        "stories_total": s.stories_total,
        "prs_merged": s.prs_merged,
        "tests_passing": s.tests_passing,
        "tests_total": s.tests_total,
        "coverage_percent": s.coverage_percent,
        "security_critical": s.security_critical,
        "security_medium": s.security_medium,
        "cost_usd": s.cost_usd,
    })


def _ser_artifact(a: Artifact) -> dict:
    return {
        "type": a.type.value,
        "path": a.path,
        "label": a.label,
        "size_bytes": a.size_bytes,
    }


def _serialize_stories(stories: tuple[StoryReport, ...]) -> str:
    return json.dumps([
        {
            "title": s.title,
            "ticket_id": s.ticket_id,
            "pr_number": s.pr_number,
            "pr_url": s.pr_url,
            "status": s.status,
            "files_changed": s.files_changed,
            "lines_added": s.lines_added,
            "lines_removed": s.lines_removed,
            "screenshots_before": [_ser_artifact(a) for a in s.screenshots_before],
            "screenshots_after": [_ser_artifact(a) for a in s.screenshots_after],
            "video": _ser_artifact(s.video) if s.video else None,
            "diff_highlights": [
                {"file_path": d.file_path, "hunk": d.hunk, "annotation": d.annotation}
                for d in s.diff_highlights
            ],
        }
        for s in stories
    ])


def _serialize_quality_gates(gates: tuple[QualityGate, ...]) -> str:
    return json.dumps([
        {"name": g.name, "status": g.status.value, "detail": g.detail}
        for g in gates
    ])


def _serialize_artifacts(artifacts: tuple[Artifact, ...]) -> str:
    return json.dumps([_ser_artifact(a) for a in artifacts])


# ── Deserialization ───────────────────────────────────────────────


def _deser_artifact(a: dict) -> Artifact:
    return Artifact(
        type=ArtifactType(a["type"]),
        path=a["path"],
        label=a["label"],
        size_bytes=a.get("size_bytes", 0),
    )


def _row_to_report(row: aiosqlite.Row) -> DemoReport:
    summary_d = json.loads(row["summary_json"]) if row["summary_json"] else {}
    stories_d = json.loads(row["stories_json"]) if row["stories_json"] else []
    quality_d = json.loads(row["quality_json"]) if row["quality_json"] else []
    learnings_d = json.loads(row["learnings_json"]) if row["learnings_json"] else []
    artifacts_d = json.loads(row["artifacts_json"]) if row["artifacts_json"] else []

    return DemoReport(
        id=row["id"],
        cycle_id=CycleId(row["cycle_id"]),
        project_id=row["project_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        summary=ReportSummary(
            stories_completed=summary_d.get("stories_completed", 0),
            stories_total=summary_d.get("stories_total", 0),
            prs_merged=summary_d.get("prs_merged", 0),
            tests_passing=summary_d.get("tests_passing", 0),
            tests_total=summary_d.get("tests_total", 0),
            coverage_percent=summary_d.get("coverage_percent", 0.0),
            security_critical=summary_d.get("security_critical", 0),
            security_medium=summary_d.get("security_medium", 0),
            cost_usd=summary_d.get("cost_usd", 0.0),
        ),
        stories=tuple(
            StoryReport(
                title=s["title"],
                ticket_id=s["ticket_id"],
                pr_number=s.get("pr_number"),
                pr_url=s.get("pr_url", ""),
                status=s["status"],
                files_changed=s.get("files_changed", 0),
                lines_added=s.get("lines_added", 0),
                lines_removed=s.get("lines_removed", 0),
                screenshots_before=tuple(
                    _deser_artifact(a) for a in s.get("screenshots_before", [])
                ),
                screenshots_after=tuple(
                    _deser_artifact(a) for a in s.get("screenshots_after", [])
                ),
                video=_deser_artifact(s["video"]) if s.get("video") else None,
                diff_highlights=tuple(
                    DiffHighlight(
                        file_path=dh["file_path"],
                        hunk=dh["hunk"],
                        annotation=dh.get("annotation", ""),
                    )
                    for dh in s.get("diff_highlights", [])
                ),
            )
            for s in stories_d
        ),
        quality_gates=tuple(
            QualityGate(
                name=g["name"],
                status=QualityStatus(g["status"]),
                detail=g.get("detail", ""),
            )
            for g in quality_d
        ),
        agent_learnings=tuple(learnings_d),
        artifacts=tuple(_deser_artifact(a) for a in artifacts_d),
    )
