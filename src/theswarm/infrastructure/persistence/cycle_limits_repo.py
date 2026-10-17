"""The owner's cycle limits (migration v041)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


class SQLiteCycleLimits:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def all(self) -> dict[str, int]:
        cursor = await self._db.execute("SELECT scope, max_cycles FROM cycle_limits")
        return {row["scope"]: int(row["max_cycles"]) for row in await cursor.fetchall()}

    async def put(self, scope: str, max_cycles: int | None, by: str = "") -> None:
        """None takes the scope back to its default."""
        if max_cycles is None:
            await self._db.execute("DELETE FROM cycle_limits WHERE scope = ?", (scope,))
        else:
            await self._db.execute(
                "INSERT OR REPLACE INTO cycle_limits (scope, max_cycles, updated_at, updated_by)"
                " VALUES (?, ?, ?, ?)",
                (scope, int(max_cycles), datetime.now(timezone.utc).isoformat(), by),
            )
        await self._db.commit()
