"""SQLite repository for anti-template (ship-bar) checks."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.designer.entities import AntiTemplateCheck
from theswarm.domain.designer.value_objects import CheckStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteAntiTemplateRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, entry: AntiTemplateCheck) -> AntiTemplateCheck:
        await self._db.execute(
            """INSERT INTO anti_template_checks
                (id, project_id, story_id, pr_url, status,
                 violations_json, qualities_json, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.project_id,
                entry.story_id,
                entry.pr_url,
                entry.status.value,
                json.dumps(list(entry.violations)),
                json.dumps(list(entry.qualities)),
                entry.summary,
                entry.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return entry

    async def get(self, entry_id: str) -> AntiTemplateCheck | None:
        cur = await self._db.execute(
            "SELECT * FROM anti_template_checks WHERE id=?", (entry_id,),
        )
        row = await cur.fetchone()
        return _row_to_atc(row) if row else None

    async def list_for_project(
        self, project_id: str, *, limit: int = 30,
    ) -> list[AntiTemplateCheck]:
        cur = await self._db.execute(
            """SELECT * FROM anti_template_checks WHERE project_id=?
             ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        )
        return [_row_to_atc(r) for r in await cur.fetchall()]

    async def latest_for_story(
        self, project_id: str, story_id: str,
    ) -> AntiTemplateCheck | None:
        cur = await self._db.execute(
            """SELECT * FROM anti_template_checks
                WHERE project_id=? AND story_id=?
             ORDER BY created_at DESC LIMIT 1""",
            (project_id, story_id),
        )
        row = await cur.fetchone()
        return _row_to_atc(row) if row else None


def _row_to_atc(row) -> AntiTemplateCheck:
    return AntiTemplateCheck(
        id=row["id"],
        project_id=row["project_id"],
        story_id=row["story_id"],
        pr_url=row["pr_url"],
        status=CheckStatus(row["status"]),
        violations=tuple(json.loads(row["violations_json"] or "[]")),
        qualities=tuple(json.loads(row["qualities_json"] or "[]")),
        summary=row["summary"],
        created_at=_dt(row["created_at"]),
    )
