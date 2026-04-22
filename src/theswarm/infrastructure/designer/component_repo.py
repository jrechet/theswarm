"""SQLite repository for component inventory entries."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.designer.entities import ComponentEntry
from theswarm.domain.designer.value_objects import ComponentStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteComponentRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, entry: ComponentEntry) -> ComponentEntry:
        existing = await self.get_for_name(entry.project_id, entry.name)
        if existing is None:
            await self._db.execute(
                """INSERT INTO design_components
                    (id, project_id, name, status, path, usage_count,
                     notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.project_id,
                    entry.name,
                    entry.status.value,
                    entry.path,
                    entry.usage_count,
                    entry.notes,
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE design_components
                      SET status=?, path=?, usage_count=?, notes=?,
                          updated_at=?
                    WHERE id=?""",
                (
                    entry.status.value,
                    entry.path,
                    entry.usage_count,
                    entry.notes,
                    entry.updated_at.isoformat(),
                    existing.id,
                ),
            )
        await self._db.commit()
        saved = await self.get_for_name(entry.project_id, entry.name)
        assert saved is not None
        return saved

    async def get_for_name(
        self, project_id: str, name: str,
    ) -> ComponentEntry | None:
        cur = await self._db.execute(
            "SELECT * FROM design_components WHERE project_id=? AND name=?",
            (project_id, name),
        )
        row = await cur.fetchone()
        return _row_to_component(row) if row else None

    async def list_for_project(
        self, project_id: str, *, active_only: bool = False,
    ) -> list[ComponentEntry]:
        if active_only:
            cur = await self._db.execute(
                """SELECT * FROM design_components
                    WHERE project_id=? AND status NOT IN ('legacy', 'deprecated')
                 ORDER BY name""",
                (project_id,),
            )
        else:
            cur = await self._db.execute(
                "SELECT * FROM design_components WHERE project_id=? ORDER BY name",
                (project_id,),
            )
        return [_row_to_component(r) for r in await cur.fetchall()]


def _row_to_component(row) -> ComponentEntry:
    return ComponentEntry(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        status=ComponentStatus(row["status"]),
        path=row["path"],
        usage_count=int(row["usage_count"] or 0),
        notes=row["notes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
