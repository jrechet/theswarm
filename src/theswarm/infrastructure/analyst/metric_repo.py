"""SQLite repository for MetricDefinition (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.analyst.entities import MetricDefinition
from theswarm.domain.analyst.value_objects import MetricKind


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteMetricDefinitionRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, m: MetricDefinition) -> MetricDefinition:
        await self._db.execute(
            """INSERT INTO metric_definitions
                (id, project_id, name, kind, unit, definition, owner, target,
                 created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, name) DO UPDATE SET
                   kind=excluded.kind,
                   unit=excluded.unit,
                   definition=excluded.definition,
                   owner=excluded.owner,
                   target=excluded.target,
                   updated_at=excluded.updated_at""",
            (
                m.id, m.project_id, m.name, m.kind.value, m.unit, m.definition,
                m.owner, m.target,
                m.created_at.isoformat(), m.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        # Return persisted row (preserves id+created_at on conflict)
        got = await self.get_for_name(m.project_id, m.name)
        return got if got is not None else m

    async def get_for_name(
        self, project_id: str, name: str,
    ) -> MetricDefinition | None:
        cur = await self._db.execute(
            "SELECT * FROM metric_definitions WHERE project_id=? AND name=?",
            (project_id, name),
        )
        row = await cur.fetchone()
        return _row_to_metric(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[MetricDefinition]:
        cur = await self._db.execute(
            """SELECT * FROM metric_definitions
                WHERE project_id=?
                ORDER BY name""",
            (project_id,),
        )
        return [_row_to_metric(r) for r in await cur.fetchall()]


def _row_to_metric(row) -> MetricDefinition:
    return MetricDefinition(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        kind=MetricKind(row["kind"]),
        unit=row["unit"],
        definition=row["definition"],
        owner=row["owner"],
        target=row["target"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
