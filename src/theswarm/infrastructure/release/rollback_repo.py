"""SQLite repository for RollbackAction (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.release.entities import RollbackAction
from theswarm.domain.release.value_objects import RollbackStatus


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _dt_or_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteRollbackActionRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, a: RollbackAction) -> RollbackAction:
        await self._db.execute(
            """INSERT INTO rollback_actions
                (id, project_id, release_version, revert_ref, status, note,
                 executed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                a.id, a.project_id, a.release_version, a.revert_ref,
                a.status.value, a.note,
                a.executed_at.isoformat() if a.executed_at else None,
                a.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return a

    async def update(self, a: RollbackAction) -> RollbackAction:
        await self._db.execute(
            """UPDATE rollback_actions
                SET revert_ref=?, status=?, note=?, executed_at=?
                WHERE id=?""",
            (
                a.revert_ref, a.status.value, a.note,
                a.executed_at.isoformat() if a.executed_at else None,
                a.id,
            ),
        )
        await self._db.commit()
        return a

    async def get_by_id(self, action_id: str) -> RollbackAction | None:
        cur = await self._db.execute(
            "SELECT * FROM rollback_actions WHERE id=?", (action_id,),
        )
        row = await cur.fetchone()
        return _row_to_action(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[RollbackAction]:
        cur = await self._db.execute(
            """SELECT * FROM rollback_actions
                WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        )
        return [_row_to_action(r) for r in await cur.fetchall()]


def _row_to_action(row) -> RollbackAction:
    return RollbackAction(
        id=row["id"],
        project_id=row["project_id"],
        release_version=row["release_version"],
        revert_ref=row["revert_ref"],
        status=RollbackStatus(row["status"]),
        note=row["note"],
        executed_at=_dt(row["executed_at"]),
        created_at=_dt_or_now(row["created_at"]),
    )
