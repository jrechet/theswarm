"""Entities for the SRE bounded context (Phase I)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.sre.value_objects import (
    CostSource,
    DeployStatus,
    IncidentSeverity,
    IncidentStatus,
)


@dataclass(frozen=True)
class Deployment:
    """A single deploy attempt for a project environment."""

    id: str
    project_id: str
    environment: str = "production"
    version: str = ""
    status: DeployStatus = DeployStatus.PENDING
    notes: str = ""
    triggered_by: str = ""
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    completed_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            DeployStatus.SUCCESS,
            DeployStatus.FAILED,
            DeployStatus.ROLLED_BACK,
        )

    @property
    def duration_seconds(self) -> float:
        if self.completed_at is None:
            return 0.0
        start = self.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = self.completed_at
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - start).total_seconds()


@dataclass(frozen=True)
class Incident:
    """A production incident tracked through its lifecycle."""

    id: str
    project_id: str
    title: str
    severity: IncidentSeverity
    status: IncidentStatus = IncidentStatus.OPEN
    summary: str = ""
    timeline: tuple[str, ...] = ()  # ordered log entries
    postmortem: str = ""
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    mitigated_at: datetime | None = None
    resolved_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.status in (
            IncidentStatus.OPEN,
            IncidentStatus.TRIAGED,
        )

    @property
    def mttr_seconds(self) -> float:
        """Mean time to resolve: detected → resolved."""
        if self.resolved_at is None:
            return 0.0
        detected = self.detected_at
        if detected.tzinfo is None:
            detected = detected.replace(tzinfo=timezone.utc)
        resolved = self.resolved_at
        if resolved.tzinfo is None:
            resolved = resolved.replace(tzinfo=timezone.utc)
        return (resolved - detected).total_seconds()

    @property
    def mttm_seconds(self) -> float:
        """Mean time to mitigate: detected → mitigated."""
        if self.mitigated_at is None:
            return 0.0
        detected = self.detected_at
        if detected.tzinfo is None:
            detected = detected.replace(tzinfo=timezone.utc)
        mitigated = self.mitigated_at
        if mitigated.tzinfo is None:
            mitigated = mitigated.replace(tzinfo=timezone.utc)
        return (mitigated - detected).total_seconds()


@dataclass(frozen=True)
class CostSample:
    """A single cost observation, unifying AI + infra spend per project."""

    id: str
    project_id: str
    source: CostSource
    amount_usd: float
    window: str = "daily"  # "daily" | "monthly" | "cycle"
    description: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
