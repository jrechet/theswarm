"""SQLite repository for critical-path patterns."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.techlead.entities import CriticalPath


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteCriticalPathRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, path: CriticalPath) -> CriticalPath:
        await self._db.execute(
            """INSERT INTO techlead_critical_paths
                (id, project_id, pattern, reason, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                path.id,
                path.project_id,
                path.pattern,
                path.reason,
                path.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return path

    async def list_for_project(self, project_id: str) -> list[CriticalPath]:
        cur = await self._db.execute(
            "SELECT * FROM techlead_critical_paths WHERE project_id=? "
            "ORDER BY created_at DESC",
            (project_id,),
        )
        return [_row_to_path(r) for r in await cur.fetchall()]

    async def delete(self, path_id: str) -> None:
        await self._db.execute(
            "DELETE FROM techlead_critical_paths WHERE id=?", (path_id,),
        )
        await self._db.commit()


def _row_to_path(row) -> CriticalPath:
    return CriticalPath(
        id=row["id"],
        project_id=row["project_id"],
        pattern=row["pattern"],
        reason=row["reason"],
        created_at=_dt(row["created_at"]),
    )
