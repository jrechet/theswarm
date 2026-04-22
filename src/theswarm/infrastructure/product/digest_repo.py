"""SQLite repository for weekly InsightDigests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.product.entities import DigestItem, InsightDigest
from theswarm.domain.product.value_objects import InsightKind


def _dt(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteDigestRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def save(self, digest: InsightDigest) -> InsightDigest:
        items = [
            {
                "kind": i.kind.value,
                "headline": i.headline,
                "body": i.body,
                "source_url": i.source_url,
            }
            for i in digest.items
        ]
        await self._db.execute(
            """INSERT INTO product_digests
                (id, project_id, week_start, narrative, items_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                digest.id,
                digest.project_id,
                digest.week_start.isoformat(),
                digest.narrative,
                json.dumps(items),
                digest.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return digest

    async def latest_for_project(self, project_id: str) -> InsightDigest | None:
        cur = await self._db.execute(
            "SELECT * FROM product_digests WHERE project_id=? "
            "ORDER BY week_start DESC LIMIT 1",
            (project_id,),
        )
        row = await cur.fetchone()
        return _row_to_digest(row) if row else None

    async def list_for_project(
        self, project_id: str, *, limit: int = 20,
    ) -> list[InsightDigest]:
        cur = await self._db.execute(
            "SELECT * FROM product_digests WHERE project_id=? "
            "ORDER BY week_start DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_digest(r) for r in await cur.fetchall()]


def _row_to_digest(row) -> InsightDigest:
    items_raw = json.loads(row["items_json"] or "[]")
    items = tuple(
        DigestItem(
            kind=InsightKind(i["kind"]),
            headline=i.get("headline", ""),
            body=i.get("body", ""),
            source_url=i.get("source_url", ""),
        )
        for i in items_raw
    )
    return InsightDigest(
        id=row["id"],
        project_id=row["project_id"],
        week_start=_dt(row["week_start"]),
        items=items,
        narrative=row["narrative"],
        created_at=_dt(row["created_at"]),
    )
