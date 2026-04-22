"""Entities for the Analyst bounded context (Phase J)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.analyst.value_objects import (
    InstrumentationStatus,
    MetricKind,
    OutcomeDirection,
)


@dataclass(frozen=True)
class MetricDefinition:
    """Per-project metric definition (name, unit, what it captures)."""

    id: str
    project_id: str
    name: str  # short key, e.g. "signup_conversion"
    kind: MetricKind
    unit: str = ""  # "%", "ms", "req/s", "$"
    definition: str = ""  # 1-2 sentence prose definition
    owner: str = ""  # team or person
    target: str = ""  # qualitative goal, e.g. ">20%"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


@dataclass(frozen=True)
class InstrumentationPlan:
    """A per-story plan for what to measure when it ships."""

    id: str
    project_id: str
    story_id: str
    metric_name: str  # references MetricDefinition.name
    hypothesis: str = ""  # "we expect signup_conversion to rise by 5%"
    method: str = ""  # "posthog funnel", "sql daily", "app log counter"
    status: InstrumentationStatus = InstrumentationStatus.PROPOSED
    note: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_blocking_outcome(self) -> bool:
        """MISSING plans block outcome verification — flag them loudly."""
        return self.status == InstrumentationStatus.MISSING


@dataclass(frozen=True)
class OutcomeObservation:
    """Did the shipped feature actually move the metric?"""

    id: str
    project_id: str
    story_id: str
    metric_name: str
    baseline: str = ""  # e.g. "18.2%"
    observed: str = ""  # e.g. "19.5%"
    direction: OutcomeDirection = OutcomeDirection.INCONCLUSIVE
    window: str = ""  # "7d post-launch", "30d"
    note: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_positive(self) -> bool:
        return self.direction == OutcomeDirection.IMPROVED
