"""Which spend alerts were posted already (migration v038)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


class SQLiteSpendAlertLedger:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def keys(self) -> set[str]:
        cursor = await self._db.execute("SELECT key FROM spend_alerts_posted")
        return {row["key"] for row in await cursor.fetchall()}

    async def add(self, key: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO spend_alerts_posted (key, posted_at) VALUES (?, ?)",
            (key, datetime.now(timezone.utc).isoformat()),
        )
        await self._db.commit()
