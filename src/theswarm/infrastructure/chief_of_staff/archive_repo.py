"""SQLite repository for ArchivedProject (Phase K)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.chief_of_staff.entities import ArchivedProject
from theswarm.domain.chief_of_staff.value_objects import ArchiveReason


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteArchivedProjectRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, a: ArchivedProject) -> ArchivedProject:
        await self._db.execute(
            """INSERT INTO archived_projects
                (id, project_id, reason, memory_frozen, export_path,
                 note, archived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                a.id, a.project_id, a.reason.value,
                1 if a.memory_frozen else 0, a.export_path, a.note,
                a.archived_at.isoformat(),
            ),
        )
        await self._db.commit()
        return a

    async def list_all(self) -> list[ArchivedProject]:
        cur = await self._db.execute(
            """SELECT * FROM archived_projects
                ORDER BY archived_at DESC""",
        )
        return [_row_to_archive(r) for r in await cur.fetchall()]

    async def get_for_project(
        self, project_id: str,
    ) -> ArchivedProject | None:
        cur = await self._db.execute(
            """SELECT * FROM archived_projects
                WHERE project_id=?
                ORDER BY archived_at DESC LIMIT 1""",
            (project_id,),
        )
        row = await cur.fetchone()
        return _row_to_archive(row) if row else None


def _row_to_archive(row) -> ArchivedProject:
    return ArchivedProject(
        id=row["id"],
        project_id=row["project_id"],
        reason=ArchiveReason(row["reason"]),
        memory_frozen=bool(row["memory_frozen"]),
        export_path=row["export_path"],
        note=row["note"],
        archived_at=_dt(row["archived_at"]),
    )
