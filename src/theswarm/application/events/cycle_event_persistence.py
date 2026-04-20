"""Event handler that persists cycle-scoped domain events for replay."""

from __future__ import annotations

import logging
from dataclasses import asdict, fields, is_dataclass
from typing import Any

from theswarm.domain.cycles.events import (
    AgentActivity,
    AgentStep,
    AgentThought,
    BudgetExceeded,
    CycleCompleted,
    CycleFailed,
    CycleStarted,
    PhaseChanged,
)
from theswarm.domain.events import DomainEvent

log = logging.getLogger(__name__)

_CYCLE_SCOPED_EVENTS: tuple[type[DomainEvent], ...] = (
    CycleStarted,
    PhaseChanged,
    AgentActivity,
    AgentThought,
    AgentStep,
    CycleCompleted,
    CycleFailed,
    BudgetExceeded,
)


class CycleEventPersistenceHandler:
    """Persist every cycle-scoped DomainEvent for replay."""

    def __init__(self, cycle_event_store: object) -> None:
        self._store = cycle_event_store

    async def handle(self, event: DomainEvent) -> None:
        if not isinstance(event, _CYCLE_SCOPED_EVENTS):
            return
        cycle_id = getattr(event, "cycle_id", None)
        if cycle_id is None:
            return
        try:
            payload = _event_payload(event)
            await self._store.append(
                cycle_id=str(cycle_id),
                event_type=type(event).__name__,
                occurred_at=event.occurred_at,
                payload=payload,
            )
        except Exception:
            log.exception("Failed to persist cycle event %s", type(event).__name__)


def _event_payload(event: DomainEvent) -> dict[str, Any]:
    if not is_dataclass(event):
        return {}
    payload: dict[str, Any] = {}
    for f in fields(event):
        value = getattr(event, f.name)
        payload[f.name] = _to_json_safe(value)
    return payload


def _to_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    if is_dataclass(value):
        return asdict(value)
    return str(value)
