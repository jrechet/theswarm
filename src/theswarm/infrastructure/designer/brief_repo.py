"""SQLite repository for design briefs (per UI story)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.designer.entities import DesignBrief
from theswarm.domain.designer.value_objects import BriefStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteDesignBriefRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, brief: DesignBrief) -> DesignBrief:
        existing = await self.get_for_story(brief.project_id, brief.story_id)
        if existing is None:
            await self._db.execute(
                """INSERT INTO design_briefs
                    (id, project_id, story_id, title, intent, hierarchy,
                     states, motion, reference_url, status, approval_note,
                     created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    brief.id,
                    brief.project_id,
                    brief.story_id,
                    brief.title,
                    brief.intent,
                    brief.hierarchy,
                    brief.states,
                    brief.motion,
                    brief.reference_url,
                    brief.status.value,
                    brief.approval_note,
                    brief.created_at.isoformat(),
                    brief.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE design_briefs
                      SET title=?, intent=?, hierarchy=?, states=?,
                          motion=?, reference_url=?, status=?,
                          approval_note=?, updated_at=?
                    WHERE id=?""",
                (
                    brief.title,
                    brief.intent,
                    brief.hierarchy,
                    brief.states,
                    brief.motion,
                    brief.reference_url,
                    brief.status.value,
                    brief.approval_note,
                    brief.updated_at.isoformat(),
                    existing.id,
                ),
            )
        await self._db.commit()
        saved = await self.get_for_story(brief.project_id, brief.story_id)
        assert saved is not None
        return saved

    async def get(self, brief_id: str) -> DesignBrief | None:
        cur = await self._db.execute(
            "SELECT * FROM design_briefs WHERE id=?", (brief_id,),
        )
        row = await cur.fetchone()
        return _row_to_brief(row) if row else None

    async def get_for_story(
        self, project_id: str, story_id: str,
    ) -> DesignBrief | None:
        cur = await self._db.execute(
            "SELECT * FROM design_briefs WHERE project_id=? AND story_id=?",
            (project_id, story_id),
        )
        row = await cur.fetchone()
        return _row_to_brief(row) if row else None

    async def list_for_project(
        self, project_id: str, *, limit: int = 50,
    ) -> list[DesignBrief]:
        cur = await self._db.execute(
            """SELECT * FROM design_briefs WHERE project_id=?
             ORDER BY updated_at DESC LIMIT ?""",
            (project_id, limit),
        )
        return [_row_to_brief(r) for r in await cur.fetchall()]


def _row_to_brief(row) -> DesignBrief:
    return DesignBrief(
        id=row["id"],
        project_id=row["project_id"],
        story_id=row["story_id"],
        title=row["title"],
        intent=row["intent"],
        hierarchy=row["hierarchy"],
        states=row["states"],
        motion=row["motion"],
        reference_url=row["reference_url"],
        status=BriefStatus(row["status"]),
        approval_note=row["approval_note"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
