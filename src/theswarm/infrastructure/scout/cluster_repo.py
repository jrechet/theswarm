"""SQLite repository for intel clusters."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.scout.entities import IntelCluster


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteIntelClusterRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, cluster: IntelCluster) -> IntelCluster:
        await self._db.execute(
            """INSERT INTO intel_clusters
                (id, topic, summary, member_ids_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                cluster.id,
                cluster.topic,
                cluster.summary,
                json.dumps(list(cluster.member_ids)),
                cluster.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return cluster

    async def set_members(self, cluster_id: str, member_ids: tuple[str, ...]) -> None:
        await self._db.execute(
            "UPDATE intel_clusters SET member_ids_json=? WHERE id=?",
            (json.dumps(list(member_ids)), cluster_id),
        )
        await self._db.commit()

    async def get(self, cluster_id: str) -> IntelCluster | None:
        cur = await self._db.execute(
            "SELECT * FROM intel_clusters WHERE id=?", (cluster_id,),
        )
        row = await cur.fetchone()
        return _row_to_cluster(row) if row else None

    async def list_recent(self, *, limit: int = 30) -> list[IntelCluster]:
        cur = await self._db.execute(
            "SELECT * FROM intel_clusters ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_cluster(r) for r in await cur.fetchall()]


def _row_to_cluster(row) -> IntelCluster:
    return IntelCluster(
        id=row["id"],
        topic=row["topic"],
        summary=row["summary"],
        member_ids=tuple(json.loads(row["member_ids_json"] or "[]")),
        created_at=_dt(row["created_at"]),
    )
