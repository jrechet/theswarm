"""SQLite repository for quarantined tests."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.qa.entities import QuarantineEntry
from theswarm.domain.qa.value_objects import QuarantineStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _dt_opt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SQLiteQuarantineRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, entry: QuarantineEntry) -> QuarantineEntry:
        await self._db.execute(
            """INSERT INTO qa_quarantine
                (id, project_id, test_id, reason, status,
                 quarantined_at, released_at, released_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.project_id,
                entry.test_id,
                entry.reason,
                entry.status.value,
                entry.quarantined_at.isoformat(),
                entry.released_at.isoformat() if entry.released_at else None,
                entry.released_reason,
            ),
        )
        await self._db.commit()
        return entry

    async def release(
        self, entry_id: str, *, reason: str, at: datetime | None = None,
    ) -> None:
        moment = (at or datetime.now(timezone.utc)).isoformat()
        await self._db.execute(
            """UPDATE qa_quarantine
                  SET status=?, released_at=?, released_reason=?
                WHERE id=?""",
            (QuarantineStatus.RELEASED.value, moment, reason, entry_id),
        )
        await self._db.commit()

    async def list_active(self, project_id: str) -> list[QuarantineEntry]:
        cur = await self._db.execute(
            "SELECT * FROM qa_quarantine WHERE project_id=? AND status=? "
            "ORDER BY quarantined_at DESC",
            (project_id, QuarantineStatus.ACTIVE.value),
        )
        return [_row_to_entry(r) for r in await cur.fetchall()]

    async def list_for_project(
        self, project_id: str, *, limit: int = 50,
    ) -> list[QuarantineEntry]:
        cur = await self._db.execute(
            "SELECT * FROM qa_quarantine WHERE project_id=? "
            "ORDER BY quarantined_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_entry(r) for r in await cur.fetchall()]


def _row_to_entry(row) -> QuarantineEntry:
    return QuarantineEntry(
        id=row["id"],
        project_id=row["project_id"],
        test_id=row["test_id"],
        reason=row["reason"],
        status=QuarantineStatus(row["status"]),
        quarantined_at=_dt(row["quarantined_at"]),
        released_at=_dt_opt(row["released_at"]),
        released_reason=row["released_reason"],
    )
