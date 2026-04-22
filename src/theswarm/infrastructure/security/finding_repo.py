"""SQLite repository for security findings."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.security.entities import SecurityFinding
from theswarm.domain.security.value_objects import FindingSeverity, FindingStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _dt_opt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SQLiteFindingRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, f: SecurityFinding) -> SecurityFinding:
        await self._db.execute(
            """INSERT INTO security_findings
                (id, project_id, severity, title, description, cve, status,
                 resolution_note, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f.id, f.project_id, f.severity.value, f.title, f.description,
                f.cve, f.status.value, f.resolution_note,
                f.created_at.isoformat(),
                f.resolved_at.isoformat() if f.resolved_at else None,
            ),
        )
        await self._db.commit()
        return f

    async def update_status(
        self, finding_id: str, status: FindingStatus, note: str,
        resolved_at: datetime | None,
    ) -> None:
        await self._db.execute(
            """UPDATE security_findings
                  SET status=?, resolution_note=?, resolved_at=?
                WHERE id=?""",
            (
                status.value, note,
                resolved_at.isoformat() if resolved_at else None,
                finding_id,
            ),
        )
        await self._db.commit()

    async def get(self, finding_id: str) -> SecurityFinding | None:
        cur = await self._db.execute(
            "SELECT * FROM security_findings WHERE id=?", (finding_id,),
        )
        row = await cur.fetchone()
        return _row_to_finding(row) if row else None

    async def list_for_project(
        self, project_id: str, open_only: bool = False,
    ) -> list[SecurityFinding]:
        if open_only:
            cur = await self._db.execute(
                """SELECT * FROM security_findings
                    WHERE project_id=? AND status IN ('open','triaged')
                    ORDER BY severity, created_at""",
                (project_id,),
            )
        else:
            cur = await self._db.execute(
                """SELECT * FROM security_findings WHERE project_id=?
                    ORDER BY created_at DESC""",
                (project_id,),
            )
        return [_row_to_finding(r) for r in await cur.fetchall()]


def _row_to_finding(row) -> SecurityFinding:
    return SecurityFinding(
        id=row["id"],
        project_id=row["project_id"],
        severity=FindingSeverity(row["severity"]),
        title=row["title"],
        description=row["description"],
        cve=row["cve"],
        status=FindingStatus(row["status"]),
        resolution_note=row["resolution_note"],
        created_at=_dt(row["created_at"]),
        resolved_at=_dt_opt(row["resolved_at"]),
    )
