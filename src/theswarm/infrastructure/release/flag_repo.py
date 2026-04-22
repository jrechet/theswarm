"""SQLite repository for FeatureFlag (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.release.entities import FeatureFlag
from theswarm.domain.release.value_objects import FlagState


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteFeatureFlagRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, f: FeatureFlag) -> FeatureFlag:
        await self._db.execute(
            """INSERT INTO feature_flags
                (id, project_id, name, owner, description, state,
                 rollout_percent, cleanup_after_days, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, name) DO UPDATE SET
                   owner=excluded.owner,
                   description=excluded.description,
                   state=excluded.state,
                   rollout_percent=excluded.rollout_percent,
                   cleanup_after_days=excluded.cleanup_after_days,
                   updated_at=excluded.updated_at""",
            (
                f.id, f.project_id, f.name, f.owner, f.description,
                f.state.value, f.rollout_percent, f.cleanup_after_days,
                f.created_at.isoformat(), f.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_for_name(f.project_id, f.name)
        return got if got is not None else f

    async def get_for_name(
        self, project_id: str, name: str,
    ) -> FeatureFlag | None:
        cur = await self._db.execute(
            "SELECT * FROM feature_flags WHERE project_id=? AND name=?",
            (project_id, name),
        )
        row = await cur.fetchone()
        return _row_to_flag(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[FeatureFlag]:
        cur = await self._db.execute(
            """SELECT * FROM feature_flags
                WHERE project_id=?
                ORDER BY state, name""",
            (project_id,),
        )
        return [_row_to_flag(r) for r in await cur.fetchall()]


def _row_to_flag(row) -> FeatureFlag:
    return FeatureFlag(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        owner=row["owner"],
        description=row["description"],
        state=FlagState(row["state"]),
        rollout_percent=row["rollout_percent"],
        cleanup_after_days=row["cleanup_after_days"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
