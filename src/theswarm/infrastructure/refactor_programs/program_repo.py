"""SQLite repository for RefactorProgram (Phase L)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.refactor_programs.entities import RefactorProgram
from theswarm.domain.refactor_programs.value_objects import (
    RefactorProgramStatus,
)


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _dt_or_none(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _pack_projects(projects: tuple[str, ...]) -> str:
    return "\n".join(p for p in projects if p)


def _unpack_projects(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(line for line in text.split("\n") if line)


class SQLiteRefactorProgramRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, p: RefactorProgram) -> RefactorProgram:
        cur = await self._db.execute(
            "SELECT id, created_at FROM refactor_programs WHERE title=?",
            (p.title,),
        )
        existing = await cur.fetchone()
        if existing:
            prog_id = existing["id"]
            created_at = _dt(existing["created_at"])
        else:
            prog_id = p.id
            created_at = p.created_at
        await self._db.execute(
            """INSERT INTO refactor_programs
                (id, title, rationale, status, target_projects_text,
                 owner, started_at, completed_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(title) DO UPDATE SET
                 rationale=excluded.rationale,
                 status=excluded.status,
                 target_projects_text=excluded.target_projects_text,
                 owner=excluded.owner,
                 started_at=excluded.started_at,
                 completed_at=excluded.completed_at,
                 updated_at=excluded.updated_at""",
            (
                prog_id, p.title, p.rationale, p.status.value,
                _pack_projects(p.target_projects), p.owner,
                p.started_at.isoformat() if p.started_at else None,
                p.completed_at.isoformat() if p.completed_at else None,
                created_at.isoformat(), p.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        return await self.get_by_title(p.title)  # type: ignore[return-value]

    async def get_by_id(self, prog_id: str) -> RefactorProgram | None:
        cur = await self._db.execute(
            "SELECT * FROM refactor_programs WHERE id=?", (prog_id,),
        )
        row = await cur.fetchone()
        return _row_to_program(row) if row else None

    async def get_by_title(self, title: str) -> RefactorProgram | None:
        cur = await self._db.execute(
            "SELECT * FROM refactor_programs WHERE title=?", (title,),
        )
        row = await cur.fetchone()
        return _row_to_program(row) if row else None

    async def list_all(self) -> list[RefactorProgram]:
        cur = await self._db.execute(
            "SELECT * FROM refactor_programs ORDER BY created_at DESC",
        )
        return [_row_to_program(r) for r in await cur.fetchall()]


def _row_to_program(row) -> RefactorProgram:
    return RefactorProgram(
        id=row["id"],
        title=row["title"],
        rationale=row["rationale"],
        status=RefactorProgramStatus(row["status"]),
        target_projects=_unpack_projects(row["target_projects_text"]),
        owner=row["owner"],
        started_at=_dt_or_none(row["started_at"]),
        completed_at=_dt_or_none(row["completed_at"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
