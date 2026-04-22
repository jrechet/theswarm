"""SQLite repository for QuickstartCheck (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.writer.entities import QuickstartCheck
from theswarm.domain.writer.value_objects import QuickstartOutcome


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteQuickstartCheckRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, q: QuickstartCheck) -> QuickstartCheck:
        await self._db.execute(
            """INSERT INTO quickstart_checks
                (id, project_id, step_count, duration_seconds, outcome,
                 failure_step, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                q.id, q.project_id, q.step_count, q.duration_seconds,
                q.outcome.value, q.failure_step, q.note,
                q.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return q

    async def list_for_project(
        self, project_id: str,
    ) -> list[QuickstartCheck]:
        cur = await self._db.execute(
            """SELECT * FROM quickstart_checks
                WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        )
        return [_row_to_check(r) for r in await cur.fetchall()]


def _row_to_check(row) -> QuickstartCheck:
    return QuickstartCheck(
        id=row["id"],
        project_id=row["project_id"],
        step_count=row["step_count"],
        duration_seconds=row["duration_seconds"],
        outcome=QuickstartOutcome(row["outcome"]),
        failure_step=row["failure_step"],
        note=row["note"],
        created_at=_dt(row["created_at"]),
    )
