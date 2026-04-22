"""SQLite repository for PortfolioADR (Phase K)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.architect.entities import PortfolioADR
from theswarm.domain.architect.value_objects import ADRStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLitePortfolioADRRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, a: PortfolioADR) -> PortfolioADR:
        await self._db.execute(
            """INSERT INTO portfolio_adrs
                (id, title, status, context, decision, consequences,
                 project_id, supersedes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                a.id, a.title, a.status.value, a.context, a.decision,
                a.consequences, a.project_id, a.supersedes,
                a.created_at.isoformat(), a.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        return a

    async def update(self, a: PortfolioADR) -> PortfolioADR:
        await self._db.execute(
            """UPDATE portfolio_adrs
                SET title=?, status=?, context=?, decision=?,
                    consequences=?, supersedes=?, updated_at=?
                WHERE id=?""",
            (
                a.title, a.status.value, a.context, a.decision,
                a.consequences, a.supersedes, a.updated_at.isoformat(),
                a.id,
            ),
        )
        await self._db.commit()
        return a

    async def get_by_id(self, adr_id: str) -> PortfolioADR | None:
        cur = await self._db.execute(
            "SELECT * FROM portfolio_adrs WHERE id=?", (adr_id,),
        )
        row = await cur.fetchone()
        return _row_to_adr(row) if row else None

    async def list_all(
        self, project_id: str | None = None,
    ) -> list[PortfolioADR]:
        if project_id is None:
            cur = await self._db.execute(
                "SELECT * FROM portfolio_adrs ORDER BY created_at DESC",
            )
        else:
            cur = await self._db.execute(
                """SELECT * FROM portfolio_adrs
                    WHERE project_id=? OR project_id=''
                    ORDER BY created_at DESC""",
                (project_id,),
            )
        return [_row_to_adr(r) for r in await cur.fetchall()]


def _row_to_adr(row) -> PortfolioADR:
    return PortfolioADR(
        id=row["id"],
        title=row["title"],
        status=ADRStatus(row["status"]),
        context=row["context"],
        decision=row["decision"],
        consequences=row["consequences"],
        project_id=row["project_id"],
        supersedes=row["supersedes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
