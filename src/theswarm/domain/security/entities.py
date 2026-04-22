"""Entities for the Security bounded context (Phase I)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from theswarm.domain.security.value_objects import (
    AuthZEffect,
    DataClass,
    FindingSeverity,
    FindingStatus,
)

# SLA deadlines per severity — how long we give ourselves to resolve.
# Critical: 1 day, High: 7 days, Medium: 30 days, Low/Info: 90 days.
_SLA_HOURS: dict[FindingSeverity, int] = {
    FindingSeverity.CRITICAL: 24,
    FindingSeverity.HIGH: 24 * 7,
    FindingSeverity.MEDIUM: 24 * 30,
    FindingSeverity.LOW: 24 * 90,
    FindingSeverity.INFO: 24 * 90,
}


@dataclass(frozen=True)
class ThreatModel:
    """Per-project threat model snapshot (assets, actors, STRIDE notes)."""

    id: str
    project_id: str
    title: str
    assets: str = ""
    actors: str = ""
    trust_boundaries: str = ""
    stride_notes: str = ""
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def freshness_days(self) -> int:
        now = datetime.now(timezone.utc)
        updated = self.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated).days

    @property
    def is_stale(self) -> bool:
        """Threat models are stale if not reviewed in 90 days."""
        return self.freshness_days > 90


@dataclass(frozen=True)
class DataInventoryEntry:
    """A single data field the project handles, tagged with classification."""

    id: str
    project_id: str
    field_name: str
    classification: DataClass
    storage_notes: str = ""
    notes: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_sensitive(self) -> bool:
        return self.classification in (
            DataClass.PII, DataClass.PAYMENT, DataClass.HEALTH,
            DataClass.CONFIDENTIAL,
        )


@dataclass(frozen=True)
class SecurityFinding:
    """An open security issue tracked against a project."""

    id: str
    project_id: str
    severity: FindingSeverity
    title: str
    description: str = ""
    cve: str = ""
    status: FindingStatus = FindingStatus.OPEN
    resolution_note: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    resolved_at: datetime | None = None

    @property
    def sla_deadline(self) -> datetime:
        hours = _SLA_HOURS[self.severity]
        base = self.created_at
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        return base + timedelta(hours=hours)

    @property
    def is_open(self) -> bool:
        return self.status in (FindingStatus.OPEN, FindingStatus.TRIAGED)

    @property
    def is_breaching_sla(self) -> bool:
        if not self.is_open:
            return False
        return datetime.now(timezone.utc) > self.sla_deadline


@dataclass(frozen=True)
class SBOMArtifact:
    """A software bill of materials attached to a cycle or snapshot."""

    id: str
    project_id: str
    cycle_id: str = ""
    tool: str = "syft"
    package_count: int = 0
    license_summary: str = ""
    artifact_path: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


@dataclass(frozen=True)
class AuthZRule:
    """A single row in the AuthZ matrix (actor × resource × action)."""

    id: str
    project_id: str
    actor_role: str
    resource: str
    action: str
    effect: AuthZEffect = AuthZEffect.ALLOW
    notes: str = ""
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.project_id, self.actor_role, self.resource, self.action)
