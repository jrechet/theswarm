"""SQLite repository for DocArtifact (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.writer.entities import DocArtifact
from theswarm.domain.writer.value_objects import DocKind, DocStatus


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _dt_or_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteDocArtifactRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, d: DocArtifact) -> DocArtifact:
        await self._db.execute(
            """INSERT INTO doc_artifacts
                (id, project_id, kind, path, title, summary, status,
                 last_reviewed_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, path) DO UPDATE SET
                   kind=excluded.kind,
                   title=excluded.title,
                   summary=excluded.summary,
                   status=excluded.status,
                   last_reviewed_at=excluded.last_reviewed_at,
                   updated_at=excluded.updated_at""",
            (
                d.id, d.project_id, d.kind.value, d.path, d.title, d.summary,
                d.status.value,
                d.last_reviewed_at.isoformat() if d.last_reviewed_at else None,
                d.created_at.isoformat(), d.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_for_path(d.project_id, d.path)
        return got if got is not None else d

    async def get_for_path(
        self, project_id: str, path: str,
    ) -> DocArtifact | None:
        cur = await self._db.execute(
            "SELECT * FROM doc_artifacts WHERE project_id=? AND path=?",
            (project_id, path),
        )
        row = await cur.fetchone()
        return _row_to_doc(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[DocArtifact]:
        cur = await self._db.execute(
            """SELECT * FROM doc_artifacts
                WHERE project_id=?
                ORDER BY kind, path""",
            (project_id,),
        )
        return [_row_to_doc(r) for r in await cur.fetchall()]


def _row_to_doc(row) -> DocArtifact:
    return DocArtifact(
        id=row["id"],
        project_id=row["project_id"],
        kind=DocKind(row["kind"]),
        path=row["path"],
        title=row["title"],
        summary=row["summary"],
        status=DocStatus(row["status"]),
        last_reviewed_at=_dt(row["last_reviewed_at"]),
        created_at=_dt_or_now(row["created_at"]),
        updated_at=_dt_or_now(row["updated_at"]),
    )
