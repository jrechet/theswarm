"""SQLite repository for QA test plans (required vs. produced archetypes)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.qa.entities import TestPlan
from theswarm.domain.qa.value_objects import TestArchetype


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _archetypes_to_json(items: tuple[TestArchetype, ...]) -> str:
    return json.dumps([a.value for a in items])


def _archetypes_from_json(raw: str | None) -> tuple[TestArchetype, ...]:
    if not raw:
        return ()
    return tuple(TestArchetype(v) for v in json.loads(raw))


class SQLiteTestPlanRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, plan: TestPlan) -> TestPlan:
        existing = await self.get_for_task(plan.project_id, plan.task_id)
        if existing is None:
            await self._db.execute(
                """INSERT INTO qa_test_plans
                    (id, project_id, task_id, required_json, produced_json,
                     notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.id,
                    plan.project_id,
                    plan.task_id,
                    _archetypes_to_json(plan.required),
                    _archetypes_to_json(plan.produced),
                    plan.notes,
                    plan.created_at.isoformat(),
                    plan.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE qa_test_plans
                      SET required_json=?, produced_json=?, notes=?, updated_at=?
                    WHERE project_id=? AND task_id=?""",
                (
                    _archetypes_to_json(plan.required),
                    _archetypes_to_json(plan.produced),
                    plan.notes,
                    plan.updated_at.isoformat(),
                    plan.project_id,
                    plan.task_id,
                ),
            )
        await self._db.commit()
        return plan

    async def get_for_task(
        self, project_id: str, task_id: str,
    ) -> TestPlan | None:
        cur = await self._db.execute(
            "SELECT * FROM qa_test_plans WHERE project_id=? AND task_id=?",
            (project_id, task_id),
        )
        row = await cur.fetchone()
        return _row_to_plan(row) if row else None

    async def list_for_project(self, project_id: str) -> list[TestPlan]:
        cur = await self._db.execute(
            "SELECT * FROM qa_test_plans WHERE project_id=? "
            "ORDER BY updated_at DESC",
            (project_id,),
        )
        return [_row_to_plan(r) for r in await cur.fetchall()]


def _row_to_plan(row) -> TestPlan:
    return TestPlan(
        id=row["id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        required=_archetypes_from_json(row["required_json"]),
        produced=_archetypes_from_json(row["produced_json"]),
        notes=row["notes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
