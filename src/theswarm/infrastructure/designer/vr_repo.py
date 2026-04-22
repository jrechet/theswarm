"""SQLite repository for visual regression records."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.designer.entities import VisualRegression
from theswarm.domain.designer.value_objects import CheckStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteVisualRegressionRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, entry: VisualRegression) -> VisualRegression:
        await self._db.execute(
            """INSERT INTO visual_regressions
                (id, project_id, story_id, viewport,
                 before_path, after_path, mask_notes,
                 status, reviewer_note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.project_id,
                entry.story_id,
                entry.viewport,
                entry.before_path,
                entry.after_path,
                entry.mask_notes,
                entry.status.value,
                entry.reviewer_note,
                entry.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return entry

    async def review(
        self, entry_id: str, *, status: CheckStatus, reviewer_note: str = "",
    ) -> None:
        await self._db.execute(
            """UPDATE visual_regressions
                  SET status=?, reviewer_note=?
                WHERE id=?""",
            (status.value, reviewer_note, entry_id),
        )
        await self._db.commit()

    async def get(self, entry_id: str) -> VisualRegression | None:
        cur = await self._db.execute(
            "SELECT * FROM visual_regressions WHERE id=?", (entry_id,),
        )
        row = await cur.fetchone()
        return _row_to_vr(row) if row else None

    async def list_for_story(
        self, project_id: str, story_id: str,
    ) -> list[VisualRegression]:
        cur = await self._db.execute(
            """SELECT * FROM visual_regressions
                WHERE project_id=? AND story_id=?
             ORDER BY created_at DESC""",
            (project_id, story_id),
        )
        return [_row_to_vr(r) for r in await cur.fetchall()]

    async def list_for_project(
        self, project_id: str, *, limit: int = 50,
    ) -> list[VisualRegression]:
        cur = await self._db.execute(
            """SELECT * FROM visual_regressions WHERE project_id=?
             ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        )
        return [_row_to_vr(r) for r in await cur.fetchall()]


def _row_to_vr(row) -> VisualRegression:
    return VisualRegression(
        id=row["id"],
        project_id=row["project_id"],
        story_id=row["story_id"],
        viewport=row["viewport"],
        before_path=row["before_path"],
        after_path=row["after_path"],
        mask_notes=row["mask_notes"],
        status=CheckStatus(row["status"]),
        reviewer_note=row["reviewer_note"],
        created_at=_dt(row["created_at"]),
    )
