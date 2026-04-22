"""SQLite repository for Dev thoughts stream."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.dev_rigour.entities import DevThought
from theswarm.domain.dev_rigour.value_objects import ThoughtKind


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteDevThoughtRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, thought: DevThought) -> DevThought:
        await self._db.execute(
            """INSERT INTO dev_thoughts
                (id, project_id, codename, kind, task_id, content, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                thought.id,
                thought.project_id,
                thought.codename,
                thought.kind.value,
                thought.task_id,
                thought.content,
                thought.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return thought

    async def list_for_project(
        self, project_id: str, *, limit: int = 50,
    ) -> list[DevThought]:
        cur = await self._db.execute(
            "SELECT * FROM dev_thoughts WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_thought(r) for r in await cur.fetchall()]

    async def list_for_task(self, task_id: str) -> list[DevThought]:
        cur = await self._db.execute(
            "SELECT * FROM dev_thoughts WHERE task_id=? "
            "ORDER BY created_at ASC",
            (task_id,),
        )
        return [_row_to_thought(r) for r in await cur.fetchall()]


def _row_to_thought(row) -> DevThought:
    return DevThought(
        id=row["id"],
        project_id=row["project_id"],
        codename=row["codename"],
        kind=ThoughtKind(row["kind"]),
        task_id=row["task_id"],
        content=row["content"],
        created_at=_dt(row["created_at"]),
    )
