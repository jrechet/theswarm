"""SQLite repository for RoutingRule (Phase K)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.chief_of_staff.entities import RoutingRule
from theswarm.domain.chief_of_staff.value_objects import RuleStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteRoutingRuleRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, r: RoutingRule) -> RoutingRule:
        await self._db.execute(
            """INSERT INTO routing_rules
                (id, pattern, target_role, target_codename, priority,
                 status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(pattern) DO UPDATE SET
                   target_role=excluded.target_role,
                   target_codename=excluded.target_codename,
                   priority=excluded.priority,
                   status=excluded.status""",
            (
                r.id, r.pattern, r.target_role, r.target_codename,
                r.priority, r.status.value, r.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_by_pattern(r.pattern)
        return got if got is not None else r

    async def get_by_pattern(self, pattern: str) -> RoutingRule | None:
        cur = await self._db.execute(
            "SELECT * FROM routing_rules WHERE pattern=?", (pattern,),
        )
        row = await cur.fetchone()
        return _row_to_rule(row) if row else None

    async def list_all(self) -> list[RoutingRule]:
        cur = await self._db.execute(
            """SELECT * FROM routing_rules
                ORDER BY priority ASC, created_at DESC""",
        )
        return [_row_to_rule(r) for r in await cur.fetchall()]

    async def list_active(self) -> list[RoutingRule]:
        cur = await self._db.execute(
            """SELECT * FROM routing_rules
                WHERE status='active'
                ORDER BY priority ASC, created_at DESC""",
        )
        return [_row_to_rule(r) for r in await cur.fetchall()]


def _row_to_rule(row) -> RoutingRule:
    return RoutingRule(
        id=row["id"],
        pattern=row["pattern"],
        target_role=row["target_role"],
        target_codename=row["target_codename"],
        priority=row["priority"],
        status=RuleStatus(row["status"]),
        created_at=_dt(row["created_at"]),
    )
