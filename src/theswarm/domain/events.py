"""Base domain event type."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""

    event_id: str = field(default_factory=lambda: uuid4().hex[:12])
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
