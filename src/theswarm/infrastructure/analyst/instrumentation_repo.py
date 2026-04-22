"""SQLite repository for InstrumentationPlan (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.analyst.entities import InstrumentationPlan
from theswarm.domain.analyst.value_objects import InstrumentationStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteInstrumentationPlanRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, p: InstrumentationPlan) -> InstrumentationPlan:
        await self._db.execute(
            """INSERT INTO instrumentation_plans
                (id, project_id, story_id, metric_name, hypothesis, method,
                 status, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, story_id, metric_name) DO UPDATE SET
                   hypothesis=excluded.hypothesis,
                   method=excluded.method,
                   status=excluded.status,
                   note=excluded.note,
                   updated_at=excluded.updated_at""",
            (
                p.id, p.project_id, p.story_id, p.metric_name, p.hypothesis,
                p.method, p.status.value, p.note,
                p.created_at.isoformat(), p.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_for_key(p.project_id, p.story_id, p.metric_name)
        return got if got is not None else p

    async def get_for_key(
        self, project_id: str, story_id: str, metric_name: str,
    ) -> InstrumentationPlan | None:
        cur = await self._db.execute(
            """SELECT * FROM instrumentation_plans
                WHERE project_id=? AND story_id=? AND metric_name=?""",
            (project_id, story_id, metric_name),
        )
        row = await cur.fetchone()
        return _row_to_plan(row) if row else None

    async def list_for_project(
        self, project_id: str, missing_only: bool = False,
    ) -> list[InstrumentationPlan]:
        if missing_only:
            cur = await self._db.execute(
                """SELECT * FROM instrumentation_plans
                    WHERE project_id=? AND status='missing'
                    ORDER BY updated_at DESC""",
                (project_id,),
            )
        else:
            cur = await self._db.execute(
                """SELECT * FROM instrumentation_plans
                    WHERE project_id=?
                    ORDER BY updated_at DESC""",
                (project_id,),
            )
        return [_row_to_plan(r) for r in await cur.fetchall()]


def _row_to_plan(row) -> InstrumentationPlan:
    return InstrumentationPlan(
        id=row["id"],
        project_id=row["project_id"],
        story_id=row["story_id"],
        metric_name=row["metric_name"],
        hypothesis=row["hypothesis"],
        method=row["method"],
        status=InstrumentationStatus(row["status"]),
        note=row["note"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
