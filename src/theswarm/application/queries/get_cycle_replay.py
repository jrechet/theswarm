"""Query for rebuilding a cycle's event stream for replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReplayFrame:
    index: int
    event_type: str
    occurred_at: datetime
    offset_ms: int
    payload: dict


class GetCycleReplayQuery:
    """Produce an ordered list of replay frames for a cycle."""

    def __init__(self, cycle_event_store: object | None) -> None:
        self._store = cycle_event_store

    async def execute(self, cycle_id: str) -> list[ReplayFrame]:
        if self._store is None:
            return []
        records = await self._store.list_for_cycle(cycle_id)
        if not records:
            return []
        first_ts = records[0].occurred_at
        frames: list[ReplayFrame] = []
        for i, record in enumerate(records):
            offset = record.occurred_at - first_ts
            offset_ms = int(offset.total_seconds() * 1000)
            frames.append(
                ReplayFrame(
                    index=i,
                    event_type=record.event_type,
                    occurred_at=record.occurred_at,
                    offset_ms=max(0, offset_ms),
                    payload=record.payload,
                ),
            )
        return frames
