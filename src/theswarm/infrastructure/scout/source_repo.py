"""SQLite repository for intel sources."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.scout.entities import IntelSource
from theswarm.domain.scout.value_objects import SourceKind


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _dt_opt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SQLiteIntelSourceRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, source: IntelSource) -> IntelSource:
        await self._db.execute(
            """INSERT INTO intel_sources
                (id, name, kind, url, project_id, enabled,
                 success_count, error_count, last_ok_at,
                 last_error, last_error_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source.id,
                source.name,
                source.kind.value,
                source.url,
                source.project_id,
                1 if source.enabled else 0,
                source.success_count,
                source.error_count,
                source.last_ok_at.isoformat() if source.last_ok_at else None,
                source.last_error,
                (source.last_error_at.isoformat()
                 if source.last_error_at else None),
                source.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return source

    async def update_health(self, source: IntelSource) -> None:
        await self._db.execute(
            """UPDATE intel_sources
                  SET success_count=?, error_count=?,
                      last_ok_at=?, last_error=?, last_error_at=?,
                      enabled=?
                WHERE id=?""",
            (
                source.success_count,
                source.error_count,
                source.last_ok_at.isoformat() if source.last_ok_at else None,
                source.last_error,
                (source.last_error_at.isoformat()
                 if source.last_error_at else None),
                1 if source.enabled else 0,
                source.id,
            ),
        )
        await self._db.commit()

    async def get(self, source_id: str) -> IntelSource | None:
        cur = await self._db.execute(
            "SELECT * FROM intel_sources WHERE id=?", (source_id,),
        )
        row = await cur.fetchone()
        return _row_to_source(row) if row else None

    async def list_all(self) -> list[IntelSource]:
        cur = await self._db.execute(
            "SELECT * FROM intel_sources ORDER BY name",
        )
        return [_row_to_source(r) for r in await cur.fetchall()]

    async def list_for_project(self, project_id: str) -> list[IntelSource]:
        cur = await self._db.execute(
            "SELECT * FROM intel_sources "
            "WHERE project_id=? OR project_id='' "
            "ORDER BY name",
            (project_id,),
        )
        return [_row_to_source(r) for r in await cur.fetchall()]


def _row_to_source(row) -> IntelSource:
    return IntelSource(
        id=row["id"],
        name=row["name"],
        kind=SourceKind(row["kind"]),
        url=row["url"],
        project_id=row["project_id"],
        enabled=bool(row["enabled"]),
        success_count=int(row["success_count"] or 0),
        error_count=int(row["error_count"] or 0),
        last_ok_at=_dt_opt(row["last_ok_at"]),
        last_error=row["last_error"],
        last_error_at=_dt_opt(row["last_error_at"]),
        created_at=_dt(row["created_at"]),
    )
