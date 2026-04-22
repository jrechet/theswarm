"""SQLite repository for SemanticMemoryEntry (Phase L)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.semantic_memory.entities import SemanticMemoryEntry


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _pack_tags(tags: tuple[str, ...]) -> str:
    return "\n".join(t for t in tags if t)


def _unpack_tags(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(line for line in text.split("\n") if line)


class SQLiteSemanticMemoryRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, e: SemanticMemoryEntry) -> SemanticMemoryEntry:
        await self._db.execute(
            """INSERT INTO semantic_memory_entries
                (id, project_id, title, content, tags_text, enabled,
                 source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                e.id, e.project_id, e.title, e.content,
                _pack_tags(e.tags), 1 if e.enabled else 0, e.source,
                e.created_at.isoformat(), e.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        return e

    async def update(self, e: SemanticMemoryEntry) -> SemanticMemoryEntry:
        await self._db.execute(
            """UPDATE semantic_memory_entries
                SET project_id=?, title=?, content=?, tags_text=?,
                    enabled=?, source=?, updated_at=?
                WHERE id=?""",
            (
                e.project_id, e.title, e.content, _pack_tags(e.tags),
                1 if e.enabled else 0, e.source, e.updated_at.isoformat(),
                e.id,
            ),
        )
        await self._db.commit()
        return e

    async def get_by_id(self, entry_id: str) -> SemanticMemoryEntry | None:
        cur = await self._db.execute(
            "SELECT * FROM semantic_memory_entries WHERE id=?", (entry_id,),
        )
        row = await cur.fetchone()
        return _row_to_entry(row) if row else None

    async def list_all(
        self, project_id: str | None = None,
    ) -> list[SemanticMemoryEntry]:
        if project_id is None:
            cur = await self._db.execute(
                """SELECT * FROM semantic_memory_entries
                    ORDER BY created_at DESC""",
            )
        else:
            cur = await self._db.execute(
                """SELECT * FROM semantic_memory_entries
                    WHERE project_id=? OR project_id=''
                    ORDER BY created_at DESC""",
                (project_id,),
            )
        return [_row_to_entry(r) for r in await cur.fetchall()]


def _row_to_entry(row) -> SemanticMemoryEntry:
    return SemanticMemoryEntry(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        content=row["content"],
        tags=_unpack_tags(row["tags_text"]),
        enabled=bool(row["enabled"]),
        source=row["source"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
