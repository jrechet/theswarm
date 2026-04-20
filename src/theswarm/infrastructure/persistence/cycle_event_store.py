"""SQLite-backed store for raw cycle events (replay source)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CycleEventRecord:
    id: int
    cycle_id: str
    event_type: str
    occurred_at: datetime
    payload: dict


class SQLiteCycleEventStore:
    """Persist cycle-scoped DomainEvents for later replay."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def append(
        self,
        cycle_id: str,
        event_type: str,
        occurred_at: datetime,
        payload: dict,
    ) -> None:
        try:
            await self._db.execute(
                "INSERT INTO cycle_events (cycle_id, event_type, occurred_at, payload_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    cycle_id,
                    event_type,
                    occurred_at.isoformat(),
                    json.dumps(payload, default=str),
                ),
            )
            await self._db.commit()
        except Exception:
            log.exception("Failed to persist cycle event %s for %s", event_type, cycle_id)

    async def list_for_cycle(self, cycle_id: str) -> list[CycleEventRecord]:
        cursor = await self._db.execute(
            "SELECT id, cycle_id, event_type, occurred_at, payload_json "
            "FROM cycle_events WHERE cycle_id = ? ORDER BY occurred_at ASC, id ASC",
            (cycle_id,),
        )
        rows = await cursor.fetchall()
        records: list[CycleEventRecord] = []
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["occurred_at"])
            except (TypeError, ValueError):
                continue
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            records.append(
                CycleEventRecord(
                    id=row["id"],
                    cycle_id=row["cycle_id"],
                    event_type=row["event_type"],
                    occurred_at=ts,
                    payload=payload,
                ),
            )
        return records
