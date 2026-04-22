"""SQLite repository for tech-debt entries."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.techlead.entities import DebtEntry
from theswarm.domain.techlead.value_objects import DebtSeverity

_SEV_ORDER = {
    DebtSeverity.CRITICAL: 0,
    DebtSeverity.HIGH: 1,
    DebtSeverity.MEDIUM: 2,
    DebtSeverity.LOW: 3,
}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteDebtRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create(self, entry: DebtEntry) -> DebtEntry:
        await self._db.execute(
            """INSERT INTO techlead_debt
                (id, project_id, title, severity, blast_radius, location,
                 owner_codename, description, resolved, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.project_id,
                entry.title,
                entry.severity.value,
                entry.blast_radius,
                entry.location,
                entry.owner_codename,
                entry.description,
                1 if entry.resolved else 0,
                entry.created_at.isoformat(),
                entry.resolved_at.isoformat() if entry.resolved_at else None,
            ),
        )
        await self._db.commit()
        return entry

    async def get(self, debt_id: str) -> DebtEntry | None:
        cur = await self._db.execute(
            "SELECT * FROM techlead_debt WHERE id=?", (debt_id,),
        )
        row = await cur.fetchone()
        return _row_to_entry(row) if row else None

    async def list_for_project(
        self,
        project_id: str,
        *,
        include_resolved: bool = False,
    ) -> list[DebtEntry]:
        if include_resolved:
            cur = await self._db.execute(
                "SELECT * FROM techlead_debt WHERE project_id=? "
                "ORDER BY resolved, created_at DESC",
                (project_id,),
            )
        else:
            cur = await self._db.execute(
                "SELECT * FROM techlead_debt WHERE project_id=? AND resolved=0 "
                "ORDER BY created_at DESC",
                (project_id,),
            )
        entries = [_row_to_entry(r) for r in await cur.fetchall()]
        # Sort by severity then age desc for UI stability.
        entries.sort(key=lambda e: (_SEV_ORDER[e.severity], -e.age_days))
        return entries

    async def resolve(self, debt_id: str) -> DebtEntry | None:
        await self._db.execute(
            "UPDATE techlead_debt SET resolved=1, resolved_at=? WHERE id=?",
            (_now_iso(), debt_id),
        )
        await self._db.commit()
        return await self.get(debt_id)

    async def delete(self, debt_id: str) -> None:
        await self._db.execute(
            "DELETE FROM techlead_debt WHERE id=?", (debt_id,),
        )
        await self._db.commit()


def _row_to_entry(row) -> DebtEntry:
    return DebtEntry(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        severity=DebtSeverity(row["severity"]),
        blast_radius=row["blast_radius"],
        location=row["location"],
        owner_codename=row["owner_codename"],
        description=row["description"],
        resolved=bool(row["resolved"]),
        created_at=_dt(row["created_at"]) or datetime.now(timezone.utc),
        resolved_at=_dt(row["resolved_at"]),
    )
