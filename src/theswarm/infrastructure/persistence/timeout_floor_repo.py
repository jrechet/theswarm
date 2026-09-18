"""Persistence for the learned CLI timeout floor (#133)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

log = logging.getLogger(__name__)

# A floor is a fact about a workspace at a point in time: its suite, its
# dependencies, the machine. Any of them can get faster, and a floor that
# never expires would keep handing a fast repository a budget it no longer
# needs — the wrong direction to be wrong in, since an oversized budget
# turns a hung call into a phase timeout with no diagnosis.
FLOOR_MAX_AGE_DAYS = 30


class SQLiteTimeoutFloorRepository:
    """Learned floors, keyed by workspace path."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def load_all(self) -> dict[str, int]:
        """Every floor still young enough to believe."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=FLOOR_MAX_AGE_DAYS)).isoformat()
        cursor = await self._conn.execute(
            "SELECT workdir, floor_seconds FROM cli_timeout_floors WHERE updated_at >= ?",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {row["workdir"]: int(row["floor_seconds"]) for row in rows}

    async def save(self, workdir: str, floor_seconds: int) -> None:
        """Raise the floor for ``workdir``. It only ever moves up."""
        await self._conn.execute(
            """
            INSERT INTO cli_timeout_floors (workdir, floor_seconds, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(workdir) DO UPDATE SET
                floor_seconds = MAX(floor_seconds, excluded.floor_seconds),
                updated_at = excluded.updated_at
            """,
            (workdir, int(floor_seconds), datetime.now(timezone.utc).isoformat()),
        )
        await self._conn.commit()
