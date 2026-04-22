"""SQLite repository for per-project Policies."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.product.entities import Policy


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLitePolicyRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, project_id: str) -> Policy | None:
        cur = await self._db.execute(
            "SELECT * FROM product_policies WHERE project_id=?", (project_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return Policy(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            body_markdown=row["body_markdown"],
            banned_terms=tuple(json.loads(row["banned_terms_json"] or "[]")),
            require_review_terms=tuple(
                json.loads(row["require_review_terms_json"] or "[]"),
            ),
            updated_at=_dt(row["updated_at"]),
            updated_by=row["updated_by"],
        )

    async def upsert(self, policy: Policy) -> Policy:
        existing = await self.get(policy.project_id)
        banned_json = json.dumps(list(policy.banned_terms))
        review_json = json.dumps(list(policy.require_review_terms))
        now = _now_iso()
        if existing:
            await self._db.execute(
                """UPDATE product_policies
                    SET title=?, body_markdown=?, banned_terms_json=?,
                        require_review_terms_json=?, updated_at=?,
                        updated_by=?, id=?
                    WHERE project_id=?""",
                (
                    policy.title,
                    policy.body_markdown,
                    banned_json,
                    review_json,
                    now,
                    policy.updated_by,
                    policy.id,
                    policy.project_id,
                ),
            )
        else:
            await self._db.execute(
                """INSERT INTO product_policies
                    (project_id, id, title, body_markdown, banned_terms_json,
                     require_review_terms_json, updated_at, updated_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    policy.project_id,
                    policy.id,
                    policy.title,
                    policy.body_markdown,
                    banned_json,
                    review_json,
                    now,
                    policy.updated_by,
                ),
            )
        await self._db.commit()
        return await self.get(policy.project_id)  # type: ignore[return-value]
