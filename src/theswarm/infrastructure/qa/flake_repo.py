"""SQLite repository for test flake tracking."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.qa.entities import FlakeRecord


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteFlakeRecordRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, record: FlakeRecord) -> FlakeRecord:
        """Insert or update by (project_id, test_id)."""
        existing = await self.get_for_test(record.project_id, record.test_id)
        if existing is None:
            await self._db.execute(
                """INSERT INTO qa_flake_records
                    (id, project_id, test_id, runs, failures,
                     last_failure_reason, last_run_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.project_id,
                    record.test_id,
                    record.runs,
                    record.failures,
                    record.last_failure_reason,
                    record.last_run_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE qa_flake_records
                      SET runs=?, failures=?, last_failure_reason=?,
                          last_run_at=?, updated_at=?
                    WHERE project_id=? AND test_id=?""",
                (
                    record.runs,
                    record.failures,
                    record.last_failure_reason,
                    record.last_run_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.project_id,
                    record.test_id,
                ),
            )
        await self._db.commit()
        return record

    async def get_for_test(
        self, project_id: str, test_id: str,
    ) -> FlakeRecord | None:
        cur = await self._db.execute(
            "SELECT * FROM qa_flake_records WHERE project_id=? AND test_id=?",
            (project_id, test_id),
        )
        row = await cur.fetchone()
        return _row_to_record(row) if row else None

    async def list_for_project(
        self, project_id: str, *, limit: int = 100,
    ) -> list[FlakeRecord]:
        cur = await self._db.execute(
            "SELECT * FROM qa_flake_records WHERE project_id=? "
            "ORDER BY updated_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_record(r) for r in await cur.fetchall()]


def _row_to_record(row) -> FlakeRecord:
    return FlakeRecord(
        id=row["id"],
        project_id=row["project_id"],
        test_id=row["test_id"],
        runs=int(row["runs"] or 0),
        failures=int(row["failures"] or 0),
        last_failure_reason=row["last_failure_reason"],
        last_run_at=_dt(row["last_run_at"]),
        updated_at=_dt(row["updated_at"]),
    )
