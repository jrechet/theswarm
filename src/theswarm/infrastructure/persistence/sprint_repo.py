"""Sprints — persistence for the composer-created issue groups."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import aiosqlite


@dataclass(frozen=True)
class Sprint:
    id: str
    project_id: str
    request: str
    issue_numbers: tuple[int, ...]
    created_at: datetime


def _new_sprint_id() -> str:
    """Short, human-recognisable id: sprint-YYYYMMDD-HHMM-XXXX."""
    now = datetime.now(timezone.utc)
    suffix = secrets.token_hex(2)
    return f"sprint-{now.strftime('%Y%m%d-%H%M')}-{suffix}"


class SQLiteSprintRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create(
        self,
        project_id: str,
        request: str,
        issue_numbers: list[int],
    ) -> Sprint:
        sid = _new_sprint_id()
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO sprints (id, project_id, request, issue_numbers_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, project_id, request, json.dumps(issue_numbers), now),
        )
        await self._db.commit()
        return Sprint(
            id=sid,
            project_id=project_id,
            request=request,
            issue_numbers=tuple(issue_numbers),
            created_at=datetime.fromisoformat(now),
        )

    async def list_for_project(self, project_id: str, limit: int = 20) -> list[Sprint]:
        cursor = await self._db.execute(
            "SELECT id, project_id, request, issue_numbers_json, created_at "
            "FROM sprints WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            Sprint(
                id=r[0],
                project_id=r[1],
                request=r[2],
                issue_numbers=tuple(json.loads(r[3]) or []),
                created_at=datetime.fromisoformat(r[4]),
            )
            for r in rows
        ]

    async def get(self, sprint_id: str) -> Sprint | None:
        cursor = await self._db.execute(
            "SELECT id, project_id, request, issue_numbers_json, created_at "
            "FROM sprints WHERE id = ?",
            (sprint_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return Sprint(
            id=row[0],
            project_id=row[1],
            request=row[2],
            issue_numbers=tuple(json.loads(row[3]) or []),
            created_at=datetime.fromisoformat(row[4]),
        )
