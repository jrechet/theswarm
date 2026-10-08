"""Demo summaries (migration v036): written once, read by the member's pages."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from theswarm.domain.reporting.summary import DemoSummary


class SQLiteDemoSummaryRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, report_id: str) -> DemoSummary | None:
        cursor = await self._db.execute("SELECT * FROM demo_summaries WHERE report_id = ?", (report_id,))
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def get_many(self, report_ids: list[str]) -> dict[str, DemoSummary]:
        ids = [i for i in dict.fromkeys(report_ids) if i]
        if not ids:
            return {}
        marks = ", ".join("?" for _ in ids)
        cursor = await self._db.execute(f"SELECT * FROM demo_summaries WHERE report_id IN ({marks})", ids)
        return {r["report_id"]: self._row(r) for r in await cursor.fetchall()}

    async def save(self, summary: DemoSummary) -> None:
        """Written again replaces the earlier row: the owner may ask twice."""
        await self._db.execute(
            """INSERT INTO demo_summaries (report_id, status, headline, body, reason, written_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(report_id) DO UPDATE SET
                 status = excluded.status, headline = excluded.headline, body = excluded.body,
                 reason = excluded.reason, written_by = excluded.written_by, created_at = excluded.created_at""",
            (summary.report_id, summary.status, summary.headline, summary.body, summary.reason,
             summary.written_by, summary.created_at.isoformat()),
        )
        await self._db.commit()

    @staticmethod
    def _row(row) -> DemoSummary:
        return DemoSummary(
            report_id=row["report_id"], status=row["status"], headline=row["headline"], body=row["body"],
            reason=row["reason"], written_by=row["written_by"], created_at=datetime.fromisoformat(row["created_at"]),
        )
