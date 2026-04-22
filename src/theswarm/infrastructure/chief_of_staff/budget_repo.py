"""SQLite repository for BudgetPolicy (Phase K)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.chief_of_staff.entities import BudgetPolicy
from theswarm.domain.chief_of_staff.value_objects import BudgetState


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteBudgetPolicyRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, p: BudgetPolicy) -> BudgetPolicy:
        await self._db.execute(
            """INSERT INTO budget_policies
                (id, project_id, daily_tokens_limit, daily_cost_usd_limit,
                 state, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id) DO UPDATE SET
                   daily_tokens_limit=excluded.daily_tokens_limit,
                   daily_cost_usd_limit=excluded.daily_cost_usd_limit,
                   state=excluded.state,
                   note=excluded.note,
                   updated_at=excluded.updated_at""",
            (
                p.id, p.project_id, p.daily_tokens_limit,
                p.daily_cost_usd_limit, p.state.value, p.note,
                p.created_at.isoformat(), p.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_for_project(p.project_id)
        return got if got is not None else p

    async def get_for_project(self, project_id: str) -> BudgetPolicy | None:
        cur = await self._db.execute(
            "SELECT * FROM budget_policies WHERE project_id=?",
            (project_id,),
        )
        row = await cur.fetchone()
        return _row_to_policy(row) if row else None

    async def list_all(self) -> list[BudgetPolicy]:
        cur = await self._db.execute(
            """SELECT * FROM budget_policies
                ORDER BY project_id ASC""",
        )
        return [_row_to_policy(r) for r in await cur.fetchall()]


def _row_to_policy(row) -> BudgetPolicy:
    return BudgetPolicy(
        id=row["id"],
        project_id=row["project_id"],
        daily_tokens_limit=row["daily_tokens_limit"],
        daily_cost_usd_limit=row["daily_cost_usd_limit"],
        state=BudgetState(row["state"]),
        note=row["note"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
