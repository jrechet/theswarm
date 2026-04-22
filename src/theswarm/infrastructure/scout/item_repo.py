"""SQLite repository for intel items (deduped by url_hash)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.scout.entities import IntelItem
from theswarm.domain.scout.value_objects import IntelCategory, IntelUrgency


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _dt_opt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SQLiteIntelItemRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, item: IntelItem) -> IntelItem | None:
        """Insert; silently returns None if the url_hash already exists."""
        try:
            await self._db.execute(
                """INSERT INTO intel_items
                    (id, source_id, title, url, url_hash, summary,
                     category, urgency, project_ids_json, cluster_id,
                     action_taken, action_taken_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id,
                    item.source_id,
                    item.title,
                    item.url,
                    item.url_hash,
                    item.summary,
                    item.category.value,
                    item.urgency.value,
                    json.dumps(list(item.project_ids)),
                    item.cluster_id,
                    item.action_taken,
                    (item.action_taken_at.isoformat()
                     if item.action_taken_at else None),
                    item.created_at.isoformat(),
                ),
            )
            await self._db.commit()
            return item
        except aiosqlite.IntegrityError:
            return None

    async def get_by_url_hash(self, url_hash: str) -> IntelItem | None:
        cur = await self._db.execute(
            "SELECT * FROM intel_items WHERE url_hash=?",
            (url_hash,),
        )
        row = await cur.fetchone()
        return _row_to_item(row) if row else None

    async def get(self, item_id: str) -> IntelItem | None:
        cur = await self._db.execute(
            "SELECT * FROM intel_items WHERE id=?", (item_id,),
        )
        row = await cur.fetchone()
        return _row_to_item(row) if row else None

    async def update_action(
        self,
        item_id: str,
        *,
        action_taken: str,
        action_taken_at: datetime | None = None,
    ) -> None:
        moment = (action_taken_at or datetime.now(timezone.utc)).isoformat()
        await self._db.execute(
            """UPDATE intel_items SET action_taken=?, action_taken_at=?
                WHERE id=?""",
            (action_taken, moment, item_id),
        )
        await self._db.commit()

    async def update_category(
        self,
        item_id: str,
        *,
        category: IntelCategory,
        urgency: IntelUrgency | None = None,
    ) -> None:
        if urgency is None:
            await self._db.execute(
                "UPDATE intel_items SET category=? WHERE id=?",
                (category.value, item_id),
            )
        else:
            await self._db.execute(
                "UPDATE intel_items SET category=?, urgency=? WHERE id=?",
                (category.value, urgency.value, item_id),
            )
        await self._db.commit()

    async def assign_cluster(self, item_id: str, cluster_id: str) -> None:
        await self._db.execute(
            "UPDATE intel_items SET cluster_id=? WHERE id=?",
            (cluster_id, item_id),
        )
        await self._db.commit()

    async def list_recent(
        self,
        *,
        limit: int = 50,
        category: IntelCategory | None = None,
        project_id: str = "",
    ) -> list[IntelItem]:
        where = []
        params: list[object] = []
        if category is not None:
            where.append("category=?")
            params.append(category.value)
        if project_id:
            # match items that list this project or portfolio items (no projects)
            where.append("(project_ids_json LIKE ? OR project_ids_json='[]')")
            params.append(f'%"{project_id}"%')
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        cur = await self._db.execute(
            f"SELECT * FROM intel_items {clause} "
            "ORDER BY created_at DESC LIMIT ?",
            tuple(params),
        )
        return [_row_to_item(r) for r in await cur.fetchall()]


def _row_to_item(row) -> IntelItem:
    return IntelItem(
        id=row["id"],
        source_id=row["source_id"],
        title=row["title"],
        url=row["url"],
        url_hash=row["url_hash"],
        summary=row["summary"],
        category=IntelCategory(row["category"]),
        urgency=IntelUrgency(row["urgency"]),
        project_ids=tuple(json.loads(row["project_ids_json"] or "[]")),
        cluster_id=row["cluster_id"],
        action_taken=row["action_taken"],
        action_taken_at=_dt_opt(row["action_taken_at"]),
        created_at=_dt(row["created_at"]),
    )
