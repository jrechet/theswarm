"""SQLite repository for product Signals."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.product.entities import Signal
from theswarm.domain.product.value_objects import SignalKind, SignalSeverity


def _dt(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteSignalRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def record(self, signal: Signal) -> Signal:
        await self._db.execute(
            """INSERT INTO product_signals
                (id, project_id, kind, severity, title, body, source_url,
                 source_name, tags_json, observed_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.id,
                signal.project_id,
                signal.kind.value,
                signal.severity.value,
                signal.title,
                signal.body,
                signal.source_url,
                signal.source_name,
                json.dumps(list(signal.tags)),
                signal.observed_at.isoformat(),
                json.dumps(dict(signal.metadata)),
            ),
        )
        await self._db.commit()
        return signal

    async def list_for_project(
        self,
        project_id: str,
        *,
        since: datetime | None = None,
        kinds: tuple[SignalKind, ...] | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        clauses = ["project_id=?"]
        args: list = [project_id]
        if since is not None:
            clauses.append("observed_at>=?")
            args.append(since.isoformat())
        if kinds:
            placeholders = ",".join(["?"] * len(kinds))
            clauses.append(f"kind IN ({placeholders})")
            args.extend(k.value for k in kinds)
        sql = (
            "SELECT * FROM product_signals WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observed_at DESC LIMIT ?"
        )
        args.append(limit)
        cur = await self._db.execute(sql, tuple(args))
        return [_row_to_signal(r) for r in await cur.fetchall()]

    async def list_recent(self, *, limit: int = 50) -> list[Signal]:
        cur = await self._db.execute(
            "SELECT * FROM product_signals ORDER BY observed_at DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_signal(r) for r in await cur.fetchall()]


def _row_to_signal(row) -> Signal:
    return Signal(
        id=row["id"],
        project_id=row["project_id"],
        kind=SignalKind(row["kind"]),
        severity=SignalSeverity(row["severity"]),
        title=row["title"],
        body=row["body"],
        source_url=row["source_url"],
        source_name=row["source_name"],
        tags=tuple(json.loads(row["tags_json"] or "[]")),
        observed_at=_dt(row["observed_at"]),
        metadata=dict(json.loads(row["metadata_json"] or "{}")),
    )
