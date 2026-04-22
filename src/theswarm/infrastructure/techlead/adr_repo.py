"""SQLite repository for Architecture Decision Records."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.techlead.entities import ADR
from theswarm.domain.techlead.value_objects import ADRStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteADRRepository:
    """Per-project ADR storage, numbered starting at 1."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def next_number(self, project_id: str) -> int:
        cur = await self._db.execute(
            "SELECT COALESCE(MAX(number), 0) AS m FROM techlead_adrs "
            "WHERE project_id=?",
            (project_id,),
        )
        row = await cur.fetchone()
        return int(row["m"] if row else 0) + 1

    async def create(self, adr: ADR) -> ADR:
        await self._db.execute(
            """INSERT INTO techlead_adrs
                (id, project_id, number, title, status, context, decision,
                 consequences, supersedes, tags_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                adr.id,
                adr.project_id,
                adr.number,
                adr.title,
                adr.status.value,
                adr.context,
                adr.decision,
                adr.consequences,
                adr.supersedes,
                json.dumps(list(adr.tags)),
                adr.created_at.isoformat(),
                adr.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        return adr

    async def update(self, adr: ADR) -> ADR:
        await self._db.execute(
            """UPDATE techlead_adrs
                SET title=?, status=?, context=?, decision=?, consequences=?,
                    supersedes=?, tags_json=?, updated_at=?
                WHERE id=?""",
            (
                adr.title,
                adr.status.value,
                adr.context,
                adr.decision,
                adr.consequences,
                adr.supersedes,
                json.dumps(list(adr.tags)),
                _now_iso(),
                adr.id,
            ),
        )
        await self._db.commit()
        got = await self.get(adr.id)
        return got or adr

    async def get(self, adr_id: str) -> ADR | None:
        cur = await self._db.execute(
            "SELECT * FROM techlead_adrs WHERE id=?", (adr_id,),
        )
        row = await cur.fetchone()
        return _row_to_adr(row) if row else None

    async def list_for_project(
        self,
        project_id: str,
        *,
        statuses: tuple[ADRStatus, ...] | None = None,
    ) -> list[ADR]:
        if statuses is None:
            cur = await self._db.execute(
                "SELECT * FROM techlead_adrs WHERE project_id=? "
                "ORDER BY number DESC",
                (project_id,),
            )
        else:
            ph = ",".join(["?"] * len(statuses))
            cur = await self._db.execute(
                f"SELECT * FROM techlead_adrs WHERE project_id=? AND status IN ({ph}) "
                f"ORDER BY number DESC",
                (project_id, *(s.value for s in statuses)),
            )
        return [_row_to_adr(r) for r in await cur.fetchall()]

    async def set_status(self, adr_id: str, status: ADRStatus) -> ADR | None:
        await self._db.execute(
            "UPDATE techlead_adrs SET status=?, updated_at=? WHERE id=?",
            (status.value, _now_iso(), adr_id),
        )
        await self._db.commit()
        return await self.get(adr_id)


def _row_to_adr(row) -> ADR:
    return ADR(
        id=row["id"],
        project_id=row["project_id"],
        number=int(row["number"]),
        title=row["title"],
        status=ADRStatus(row["status"]),
        context=row["context"],
        decision=row["decision"],
        consequences=row["consequences"],
        supersedes=row["supersedes"],
        tags=tuple(json.loads(row["tags_json"] or "[]")),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
