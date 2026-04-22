"""SQLite repository for ReleaseVersion (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.release.entities import ReleaseVersion
from theswarm.domain.release.value_objects import ReleaseStatus


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _dt_or_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteReleaseVersionRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, r: ReleaseVersion) -> ReleaseVersion:
        await self._db.execute(
            """INSERT INTO release_versions
                (id, project_id, version, status, summary, released_at,
                 created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, version) DO UPDATE SET
                   status=excluded.status,
                   summary=excluded.summary,
                   released_at=excluded.released_at,
                   updated_at=excluded.updated_at""",
            (
                r.id, r.project_id, r.version, r.status.value, r.summary,
                r.released_at.isoformat() if r.released_at else None,
                r.created_at.isoformat(), r.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_for_version(r.project_id, r.version)
        return got if got is not None else r

    async def get_for_version(
        self, project_id: str, version: str,
    ) -> ReleaseVersion | None:
        cur = await self._db.execute(
            "SELECT * FROM release_versions WHERE project_id=? AND version=?",
            (project_id, version),
        )
        row = await cur.fetchone()
        return _row_to_version(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[ReleaseVersion]:
        cur = await self._db.execute(
            """SELECT * FROM release_versions
                WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        )
        return [_row_to_version(r) for r in await cur.fetchall()]


def _row_to_version(row) -> ReleaseVersion:
    return ReleaseVersion(
        id=row["id"],
        project_id=row["project_id"],
        version=row["version"],
        status=ReleaseStatus(row["status"]),
        summary=row["summary"],
        released_at=_dt(row["released_at"]),
        created_at=_dt_or_now(row["created_at"]),
        updated_at=_dt_or_now(row["updated_at"]),
    )
