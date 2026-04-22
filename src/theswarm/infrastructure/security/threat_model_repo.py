"""SQLite repository for threat models."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.security.entities import ThreatModel


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteThreatModelRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, tm: ThreatModel) -> ThreatModel:
        existing = await self.get_for_project(tm.project_id)
        if existing is None:
            await self._db.execute(
                """INSERT INTO threat_models
                    (id, project_id, title, assets, actors, trust_boundaries,
                     stride_notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tm.id, tm.project_id, tm.title, tm.assets, tm.actors,
                    tm.trust_boundaries, tm.stride_notes,
                    tm.created_at.isoformat(), tm.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE threat_models
                      SET title=?, assets=?, actors=?, trust_boundaries=?,
                          stride_notes=?, updated_at=?
                    WHERE id=?""",
                (
                    tm.title, tm.assets, tm.actors, tm.trust_boundaries,
                    tm.stride_notes, tm.updated_at.isoformat(), existing.id,
                ),
            )
        await self._db.commit()
        saved = await self.get_for_project(tm.project_id)
        assert saved is not None
        return saved

    async def get_for_project(self, project_id: str) -> ThreatModel | None:
        cur = await self._db.execute(
            "SELECT * FROM threat_models WHERE project_id=?", (project_id,),
        )
        row = await cur.fetchone()
        return _row_to_tm(row) if row else None


def _row_to_tm(row) -> ThreatModel:
    return ThreatModel(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        assets=row["assets"],
        actors=row["actors"],
        trust_boundaries=row["trust_boundaries"],
        stride_notes=row["stride_notes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
