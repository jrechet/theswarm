"""In-process event bus for domain events."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

from theswarm.domain.events import DomainEvent

log = logging.getLogger(__name__)

EventHandler = Callable[[DomainEvent], Coroutine[Any, Any, None]]


class EventBus:
    """Simple in-process pub/sub for domain events.

    Both TUI and Web subscribe to the same event stream.
    Handlers are called concurrently via asyncio.gather.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events (useful for logging, SSE streaming)."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        """Remove a handler for a specific event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Remove a global handler."""
        if handler in self._global_handlers:
            self._global_handlers.remove(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Publish an event to all matching subscribers."""
        handlers = list(self._handlers.get(type(event), []))
        handlers.extend(self._global_handlers)

        if not handlers:
            return

        results = await asyncio.gather(
            *(self._safe_call(h, event) for h in handlers),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                log.error("Event handler error for %s: %s", type(event).__name__, result)

    async def _safe_call(self, handler: EventHandler, event: DomainEvent) -> None:
        try:
            await handler(event)
        except Exception:
            log.exception("Event handler failed for %s", type(event).__name__)
            raise

    @property
    def handler_count(self) -> int:
        total = len(self._global_handlers)
        for handlers in self._handlers.values():
            total += len(handlers)
        return total

    def clear(self) -> None:
        """Remove all handlers."""
        self._handlers.clear()
        self._global_handlers.clear()
