"""SQLite repository for coverage deltas."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.dev_rigour.entities import CoverageDelta


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteCoverageDeltaRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, delta: CoverageDelta) -> CoverageDelta:
        await self._db.execute(
            """INSERT INTO dev_coverage_deltas
                (id, project_id, pr_url, task_id, codename,
                 total_before_pct, total_after_pct, changed_lines_pct,
                 changed_lines, missed_lines, threshold_pct, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                delta.id,
                delta.project_id,
                delta.pr_url,
                delta.task_id,
                delta.codename,
                delta.total_before_pct,
                delta.total_after_pct,
                delta.changed_lines_pct,
                delta.changed_lines,
                delta.missed_lines,
                delta.threshold_pct,
                delta.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return delta

    async def list_for_project(
        self, project_id: str, *, limit: int = 20,
    ) -> list[CoverageDelta]:
        cur = await self._db.execute(
            "SELECT * FROM dev_coverage_deltas WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_delta(r) for r in await cur.fetchall()]

    async def latest_for_pr(self, pr_url: str) -> CoverageDelta | None:
        cur = await self._db.execute(
            "SELECT * FROM dev_coverage_deltas WHERE pr_url=? "
            "ORDER BY created_at DESC LIMIT 1",
            (pr_url,),
        )
        row = await cur.fetchone()
        return _row_to_delta(row) if row else None


def _row_to_delta(row) -> CoverageDelta:
    return CoverageDelta(
        id=row["id"],
        project_id=row["project_id"],
        pr_url=row["pr_url"],
        task_id=row["task_id"],
        codename=row["codename"],
        total_before_pct=row["total_before_pct"],
        total_after_pct=row["total_after_pct"],
        changed_lines_pct=row["changed_lines_pct"],
        changed_lines=row["changed_lines"],
        missed_lines=row["missed_lines"],
        threshold_pct=row["threshold_pct"],
        created_at=_dt(row["created_at"]),
    )
