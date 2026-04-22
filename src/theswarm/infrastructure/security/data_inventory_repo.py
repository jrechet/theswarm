"""SQLite repository for data inventory entries."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.security.entities import DataInventoryEntry
from theswarm.domain.security.value_objects import DataClass


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteDataInventoryRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, entry: DataInventoryEntry) -> DataInventoryEntry:
        existing = await self.get_for_field(entry.project_id, entry.field_name)
        if existing is None:
            await self._db.execute(
                """INSERT INTO data_inventory
                    (id, project_id, field_name, classification, storage_notes,
                     notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id, entry.project_id, entry.field_name,
                    entry.classification.value, entry.storage_notes, entry.notes,
                    entry.created_at.isoformat(), entry.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE data_inventory
                      SET classification=?, storage_notes=?, notes=?, updated_at=?
                    WHERE id=?""",
                (
                    entry.classification.value, entry.storage_notes,
                    entry.notes, entry.updated_at.isoformat(), existing.id,
                ),
            )
        await self._db.commit()
        saved = await self.get_for_field(entry.project_id, entry.field_name)
        assert saved is not None
        return saved

    async def get_for_field(
        self, project_id: str, field_name: str,
    ) -> DataInventoryEntry | None:
        cur = await self._db.execute(
            "SELECT * FROM data_inventory WHERE project_id=? AND field_name=?",
            (project_id, field_name),
        )
        row = await cur.fetchone()
        return _row_to_entry(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[DataInventoryEntry]:
        cur = await self._db.execute(
            """SELECT * FROM data_inventory WHERE project_id=?
               ORDER BY classification DESC, field_name""",
            (project_id,),
        )
        return [_row_to_entry(r) for r in await cur.fetchall()]


def _row_to_entry(row) -> DataInventoryEntry:
    return DataInventoryEntry(
        id=row["id"],
        project_id=row["project_id"],
        field_name=row["field_name"],
        classification=DataClass(row["classification"]),
        storage_notes=row["storage_notes"],
        notes=row["notes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
