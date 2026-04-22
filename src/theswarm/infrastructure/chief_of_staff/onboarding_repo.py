"""SQLite repository for OnboardingStep (Phase K)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.chief_of_staff.entities import OnboardingStep
from theswarm.domain.chief_of_staff.value_objects import OnboardingStatus


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _dt_required(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteOnboardingStepRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, s: OnboardingStep) -> OnboardingStep:
        await self._db.execute(
            """INSERT INTO onboarding_steps
                (id, project_id, step_name, step_order, status, note,
                 completed_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, step_name) DO UPDATE SET
                   step_order=excluded.step_order,
                   status=excluded.status,
                   note=excluded.note,
                   completed_at=excluded.completed_at""",
            (
                s.id, s.project_id, s.step_name, s.order,
                s.status.value, s.note,
                s.completed_at.isoformat() if s.completed_at else None,
                s.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_for_step(s.project_id, s.step_name)
        return got if got is not None else s

    async def get_for_step(
        self, project_id: str, step_name: str,
    ) -> OnboardingStep | None:
        cur = await self._db.execute(
            """SELECT * FROM onboarding_steps
                WHERE project_id=? AND step_name=?""",
            (project_id, step_name),
        )
        row = await cur.fetchone()
        return _row_to_step(row) if row else None

    async def list_for_project(
        self, project_id: str,
    ) -> list[OnboardingStep]:
        cur = await self._db.execute(
            """SELECT * FROM onboarding_steps
                WHERE project_id=?
                ORDER BY step_order ASC, created_at ASC""",
            (project_id,),
        )
        return [_row_to_step(r) for r in await cur.fetchall()]


def _row_to_step(row) -> OnboardingStep:
    return OnboardingStep(
        id=row["id"],
        project_id=row["project_id"],
        step_name=row["step_name"],
        order=row["step_order"],
        status=OnboardingStatus(row["status"]),
        note=row["note"],
        completed_at=_dt(row["completed_at"]),
        created_at=_dt_required(row["created_at"]),
    )
