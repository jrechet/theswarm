"""SQLite repository for DirectionBrief (Phase K)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.architect.entities import DirectionBrief
from theswarm.domain.architect.value_objects import BriefScope


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _tuple_to_text(items: tuple[str, ...]) -> str:
    return "\n".join(i for i in items if i)


def _text_to_tuple(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(ln for ln in text.splitlines() if ln)


class SQLiteDirectionBriefRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, b: DirectionBrief) -> DirectionBrief:
        await self._db.execute(
            """INSERT INTO direction_briefs
                (id, title, scope, project_id, period, author,
                 focus_areas_text, risks_text, narrative, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                b.id, b.title, b.scope.value, b.project_id, b.period,
                b.author, _tuple_to_text(b.focus_areas),
                _tuple_to_text(b.risks), b.narrative,
                b.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return b

    async def list_portfolio(self) -> list[DirectionBrief]:
        cur = await self._db.execute(
            """SELECT * FROM direction_briefs
                WHERE scope='portfolio'
                ORDER BY created_at DESC""",
        )
        return [_row_to_brief(r) for r in await cur.fetchall()]

    async def list_for_project(
        self, project_id: str,
    ) -> list[DirectionBrief]:
        cur = await self._db.execute(
            """SELECT * FROM direction_briefs
                WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        )
        return [_row_to_brief(r) for r in await cur.fetchall()]


def _row_to_brief(row) -> DirectionBrief:
    return DirectionBrief(
        id=row["id"],
        title=row["title"],
        scope=BriefScope(row["scope"]),
        project_id=row["project_id"],
        period=row["period"],
        author=row["author"],
        focus_areas=_text_to_tuple(row["focus_areas_text"]),
        risks=_text_to_tuple(row["risks_text"]),
        narrative=row["narrative"],
        created_at=_dt(row["created_at"]),
    )
