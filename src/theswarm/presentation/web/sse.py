"""Server-Sent Events hub for real-time dashboard updates."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from theswarm.domain.events import DomainEvent

log = logging.getLogger(__name__)


class SSEHub:
    """Fan-out SSE broadcaster.

    The EventBus publishes DomainEvents here. Each connected browser
    receives a JSON-encoded event via SSE.
    """

    def __init__(self, max_history: int = 100) -> None:
        self._queues: list[asyncio.Queue[str]] = []
        self._history: list[str] = []
        self._max_history = max_history

    def connect(self) -> asyncio.Queue[str]:
        """Register a new SSE client. Returns a queue to read from."""
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        self._queues.append(q)
        return q

    def disconnect(self, queue: asyncio.Queue[str]) -> None:
        """Remove a disconnected client."""
        if queue in self._queues:
            self._queues.remove(queue)

    @property
    def client_count(self) -> int:
        return len(self._queues)

    @property
    def history(self) -> list[str]:
        return list(self._history)

    async def broadcast(self, event: DomainEvent) -> None:
        """Convert domain event to SSE payload and fan out to all clients."""
        payload = json.dumps({
            "type": type(event).__name__,
            "event_id": event.event_id,
            "occurred_at": event.occurred_at.isoformat(),
            **{
                k: _serialize(v)
                for k, v in event.__dict__.items()
                if k not in ("event_id", "occurred_at")
            },
        })

        self._history.append(payload)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        dead: list[asyncio.Queue[str]] = []
        for q in self._queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)

        for q in dead:
            self.disconnect(q)

    async def event_stream(self, queue: asyncio.Queue[str]) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted messages from a client queue."""
        try:
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self.disconnect(queue)


def _serialize(v: object) -> object:
    """Convert domain types to JSON-safe values."""
    if isinstance(v, datetime):
        return v.isoformat()
    if hasattr(v, "value"):
        return str(v.value) if hasattr(v.value, '__str__') else v.value
    if isinstance(v, dict):
        return {k: _serialize(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_serialize(item) for item in v]
    return v
