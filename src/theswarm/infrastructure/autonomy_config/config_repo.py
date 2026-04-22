"""SQLite repository for AutonomyConfig (Phase L)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.autonomy_config.entities import AutonomyConfig
from theswarm.domain.autonomy_config.value_objects import AutonomyLevel


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteAutonomyConfigRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, c: AutonomyConfig) -> AutonomyConfig:
        cur = await self._db.execute(
            "SELECT id FROM autonomy_configs WHERE project_id=? AND role=?",
            (c.project_id, c.role),
        )
        existing = await cur.fetchone()
        cfg_id = existing["id"] if existing else c.id
        await self._db.execute(
            """INSERT INTO autonomy_configs
                (id, project_id, role, level, note, updated_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, role) DO UPDATE SET
                 level=excluded.level,
                 note=excluded.note,
                 updated_by=excluded.updated_by,
                 updated_at=excluded.updated_at""",
            (
                cfg_id, c.project_id, c.role, c.level.value, c.note,
                c.updated_by, c.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        return await self.get(c.project_id, c.role)  # type: ignore[return-value]

    async def get(
        self, project_id: str, role: str,
    ) -> AutonomyConfig | None:
        cur = await self._db.execute(
            "SELECT * FROM autonomy_configs WHERE project_id=? AND role=?",
            (project_id, role),
        )
        row = await cur.fetchone()
        return _row_to_config(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[AutonomyConfig]:
        cur = await self._db.execute(
            """SELECT * FROM autonomy_configs WHERE project_id=?
                ORDER BY role ASC""",
            (project_id,),
        )
        return [_row_to_config(r) for r in await cur.fetchall()]

    async def list_all(self) -> list[AutonomyConfig]:
        cur = await self._db.execute(
            """SELECT * FROM autonomy_configs
                ORDER BY project_id ASC, role ASC""",
        )
        return [_row_to_config(r) for r in await cur.fetchall()]


def _row_to_config(row) -> AutonomyConfig:
    return AutonomyConfig(
        id=row["id"],
        project_id=row["project_id"],
        role=row["role"],
        level=AutonomyLevel(row["level"]),
        note=row["note"],
        updated_by=row["updated_by"],
        updated_at=_dt(row["updated_at"]),
    )
