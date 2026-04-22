"""SQLite repository for OutcomeObservation (Phase J)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.analyst.entities import OutcomeObservation
from theswarm.domain.analyst.value_objects import OutcomeDirection


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteOutcomeObservationRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, o: OutcomeObservation) -> OutcomeObservation:
        await self._db.execute(
            """INSERT INTO outcome_observations
                (id, project_id, story_id, metric_name, baseline, observed,
                 direction, window, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                o.id, o.project_id, o.story_id, o.metric_name, o.baseline,
                o.observed, o.direction.value, o.window, o.note,
                o.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return o

    async def list_for_project(
        self, project_id: str,
    ) -> list[OutcomeObservation]:
        cur = await self._db.execute(
            """SELECT * FROM outcome_observations
                WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        )
        return [_row_to_outcome(r) for r in await cur.fetchall()]

    async def list_for_story(
        self, project_id: str, story_id: str,
    ) -> list[OutcomeObservation]:
        cur = await self._db.execute(
            """SELECT * FROM outcome_observations
                WHERE project_id=? AND story_id=?
                ORDER BY created_at DESC""",
            (project_id, story_id),
        )
        return [_row_to_outcome(r) for r in await cur.fetchall()]


def _row_to_outcome(row) -> OutcomeObservation:
    return OutcomeObservation(
        id=row["id"],
        project_id=row["project_id"],
        story_id=row["story_id"],
        metric_name=row["metric_name"],
        baseline=row["baseline"],
        observed=row["observed"],
        direction=OutcomeDirection(row["direction"]),
        window=row["window"],
        note=row["note"],
        created_at=_dt(row["created_at"]),
    )
