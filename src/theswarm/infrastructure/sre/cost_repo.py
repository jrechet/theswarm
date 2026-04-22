"""SQLite repository for cost samples."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.sre.entities import CostSample
from theswarm.domain.sre.value_objects import CostSource


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteCostRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, s: CostSample) -> CostSample:
        await self._db.execute(
            """INSERT INTO cost_samples
                (id, project_id, source, amount_usd, window, description,
                 created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                s.id, s.project_id, s.source.value, s.amount_usd, s.window,
                s.description, s.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return s

    async def list_for_project(
        self, project_id: str, limit: int = 100,
    ) -> list[CostSample]:
        cur = await self._db.execute(
            """SELECT * FROM cost_samples WHERE project_id=?
                ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        )
        return [_row_to_sample(r) for r in await cur.fetchall()]

    async def rollup_by_source(
        self, project_id: str,
    ) -> dict[str, float]:
        """Sum amount_usd grouped by source for a project."""
        cur = await self._db.execute(
            """SELECT source, SUM(amount_usd) AS total
                 FROM cost_samples WHERE project_id=?
                 GROUP BY source""",
            (project_id,),
        )
        rows = await cur.fetchall()
        return {r["source"]: float(r["total"] or 0) for r in rows}


def _row_to_sample(row) -> CostSample:
    return CostSample(
        id=row["id"],
        project_id=row["project_id"],
        source=CostSource(row["source"]),
        amount_usd=float(row["amount_usd"]),
        window=row["window"],
        description=row["description"],
        created_at=_dt(row["created_at"]),
    )
