"""The messages said to a cycle (migration v042)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SQLiteCycleInbox:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, cycle_id: str, body: str, author: str, urgent: bool = False) -> int:
        cursor = await self._db.execute(
            "INSERT INTO cycle_inbox (cycle_id, body, author, urgent, created_at) VALUES (?, ?, ?, ?, ?)",
            (cycle_id, body, author, 1 if urgent else 0, _now()),
        )
        await self._db.commit()
        return int(cursor.lastrowid or 0)

    async def take(self, cycle_id: str, to: str, urgent_only: bool = False) -> list[str]:
        """The messages not yet read, oldest first, marked read by `to` —
        with `urgent_only`, those that stop a call and no other."""
        cursor = await self._db.execute(
            "SELECT id, body FROM cycle_inbox WHERE cycle_id = ? AND delivered_at IS NULL"
            + (" AND urgent = 1" if urgent_only else "") + " ORDER BY id",
            (cycle_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return []
        marks = ",".join("?" for _ in rows)
        await self._db.execute(
            f"UPDATE cycle_inbox SET delivered_at = ?, delivered_to = ? WHERE id IN ({marks})",  # noqa: S608 — placeholders only
            (_now(), to, *(row[0] for row in rows)),
        )
        await self._db.commit()
        return [str(row[1]) for row in rows]

    async def waiting(self, cycle_id: str) -> int:
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM cycle_inbox WHERE cycle_id = ? AND delivered_at IS NULL", (cycle_id,),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
