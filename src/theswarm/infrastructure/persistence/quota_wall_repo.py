"""Persistence for the closed Claude subscription window (`tools/quota_wall`)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


class SQLiteQuotaWallRepository:
    """One row: when the window reopens, and the message that said so."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def load(self) -> tuple[datetime, str] | None:
        cursor = await self._conn.execute("SELECT until_utc, reason FROM quota_wall WHERE id = 1")
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return datetime.fromisoformat(row["until_utc"]), row["reason"] or ""

    async def save(self, until: datetime, reason: str) -> None:
        await self._conn.execute(
            """
            INSERT INTO quota_wall (id, until_utc, reason, updated_at) VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                until_utc = excluded.until_utc,
                reason = excluded.reason,
                updated_at = excluded.updated_at
            """,
            (until.isoformat(), reason[:1000], datetime.now(timezone.utc).isoformat()),
        )
        await self._conn.commit()
