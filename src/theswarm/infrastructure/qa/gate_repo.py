"""SQLite repository for quality gate results."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.qa.entities import QualityGate
from theswarm.domain.qa.value_objects import GateName, GateStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteQualityGateRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, gate: QualityGate) -> QualityGate:
        await self._db.execute(
            """INSERT INTO qa_quality_gates
                (id, project_id, gate, status, summary, pr_url, task_id,
                 score, finding_count, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                gate.id,
                gate.project_id,
                gate.gate.value,
                gate.status.value,
                gate.summary,
                gate.pr_url,
                gate.task_id,
                gate.score,
                gate.finding_count,
                gate.details_json,
                gate.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return gate

    async def latest_for_gate(
        self, project_id: str, gate: GateName,
    ) -> QualityGate | None:
        cur = await self._db.execute(
            "SELECT * FROM qa_quality_gates "
            "WHERE project_id=? AND gate=? "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id, gate.value),
        )
        row = await cur.fetchone()
        return _row_to_gate(row) if row else None

    async def list_for_project(
        self, project_id: str, *, limit: int = 50,
    ) -> list[QualityGate]:
        cur = await self._db.execute(
            "SELECT * FROM qa_quality_gates WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_gate(r) for r in await cur.fetchall()]


def _row_to_gate(row) -> QualityGate:
    return QualityGate(
        id=row["id"],
        project_id=row["project_id"],
        gate=GateName(row["gate"]),
        status=GateStatus(row["status"]),
        summary=row["summary"],
        pr_url=row["pr_url"],
        task_id=row["task_id"],
        score=row["score"],
        finding_count=int(row["finding_count"] or 0),
        details_json=row["details_json"] or "{}",
        created_at=_dt(row["created_at"]),
    )
