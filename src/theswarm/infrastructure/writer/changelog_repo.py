"""SQLite repository for ChangelogEntry (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.writer.entities import ChangelogEntry
from theswarm.domain.writer.value_objects import ChangeKind


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteChangelogEntryRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, c: ChangelogEntry) -> ChangelogEntry:
        await self._db.execute(
            """INSERT INTO changelog_entries
                (id, project_id, kind, summary, pr_url, version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                c.id, c.project_id, c.kind.value, c.summary, c.pr_url,
                c.version, c.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return c

    async def list_for_project(
        self, project_id: str,
    ) -> list[ChangelogEntry]:
        cur = await self._db.execute(
            """SELECT * FROM changelog_entries
                WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        )
        return [_row_to_entry(r) for r in await cur.fetchall()]

    async def list_for_version(
        self, project_id: str, version: str,
    ) -> list[ChangelogEntry]:
        cur = await self._db.execute(
            """SELECT * FROM changelog_entries
                WHERE project_id=? AND version=?
                ORDER BY created_at""",
            (project_id, version),
        )
        return [_row_to_entry(r) for r in await cur.fetchall()]

    async def list_unreleased(
        self, project_id: str,
    ) -> list[ChangelogEntry]:
        cur = await self._db.execute(
            """SELECT * FROM changelog_entries
                WHERE project_id=? AND version=''
                ORDER BY created_at""",
            (project_id,),
        )
        return [_row_to_entry(r) for r in await cur.fetchall()]


def _row_to_entry(row) -> ChangelogEntry:
    return ChangelogEntry(
        id=row["id"],
        project_id=row["project_id"],
        kind=ChangeKind(row["kind"]),
        summary=row["summary"],
        pr_url=row["pr_url"],
        version=row["version"],
        created_at=_dt(row["created_at"]),
    )
