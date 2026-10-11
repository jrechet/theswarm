"""The cycles waiting their turn (migration v040), so a restart keeps them."""

from __future__ import annotations

import aiosqlite


class SQLiteCycleQueue:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, cycle_id: str, repo: str, issue_number: int | None, description: str,
                  queued_at: str) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO cycle_queue (id, repo, issue_number, description, queued_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (cycle_id, repo, issue_number, description, queued_at),
        )
        await self._db.commit()

    async def remove(self, cycle_id: str) -> None:
        await self._db.execute("DELETE FROM cycle_queue WHERE id = ?", (cycle_id,))
        await self._db.commit()

    async def list_all(self) -> list[dict]:
        """Oldest first: the order they were queued in, the order they start in."""
        cursor = await self._db.execute(
            "SELECT id, repo, issue_number, description, queued_at FROM cycle_queue ORDER BY queued_at, rowid",
        )
        return [dict(row) for row in await cursor.fetchall()]
