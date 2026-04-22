"""SQLite repository for AuthZ matrix rules."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.security.entities import AuthZRule
from theswarm.domain.security.value_objects import AuthZEffect


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteAuthZRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, rule: AuthZRule) -> AuthZRule:
        existing = await self.get_for_key(
            rule.project_id, rule.actor_role, rule.resource, rule.action,
        )
        if existing is None:
            await self._db.execute(
                """INSERT INTO authz_rules
                    (id, project_id, actor_role, resource, action, effect,
                     notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rule.id, rule.project_id, rule.actor_role, rule.resource,
                    rule.action, rule.effect.value, rule.notes,
                    rule.created_at.isoformat(), rule.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE authz_rules
                      SET effect=?, notes=?, updated_at=?
                    WHERE id=?""",
                (
                    rule.effect.value, rule.notes,
                    rule.updated_at.isoformat(), existing.id,
                ),
            )
        await self._db.commit()
        saved = await self.get_for_key(
            rule.project_id, rule.actor_role, rule.resource, rule.action,
        )
        assert saved is not None
        return saved

    async def get_for_key(
        self, project_id: str, actor_role: str, resource: str, action: str,
    ) -> AuthZRule | None:
        cur = await self._db.execute(
            """SELECT * FROM authz_rules
                WHERE project_id=? AND actor_role=? AND resource=? AND action=?""",
            (project_id, actor_role, resource, action),
        )
        row = await cur.fetchone()
        return _row_to_rule(row) if row else None

    async def list_for_project(self, project_id: str) -> list[AuthZRule]:
        cur = await self._db.execute(
            """SELECT * FROM authz_rules WHERE project_id=?
                ORDER BY actor_role, resource, action""",
            (project_id,),
        )
        return [_row_to_rule(r) for r in await cur.fetchall()]

    async def delete(self, rule_id: str) -> None:
        await self._db.execute(
            "DELETE FROM authz_rules WHERE id=?", (rule_id,),
        )
        await self._db.commit()


def _row_to_rule(row) -> AuthZRule:
    return AuthZRule(
        id=row["id"],
        project_id=row["project_id"],
        actor_role=row["actor_role"],
        resource=row["resource"],
        action=row["action"],
        effect=AuthZEffect(row["effect"]),
        notes=row["notes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
