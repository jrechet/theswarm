"""Value objects for the SRE bounded context (Phase I)."""

from __future__ import annotations

from enum import Enum


class DeployStatus(str, Enum):
    """Deploy lifecycle."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class IncidentSeverity(str, Enum):
    """Severity tier for an incident."""

    SEV1 = "sev1"  # outage / data loss
    SEV2 = "sev2"  # major feature impacted
    SEV3 = "sev3"  # minor impact
    SEV4 = "sev4"  # informational


class IncidentStatus(str, Enum):
    """Incident lifecycle."""

    OPEN = "open"
    TRIAGED = "triaged"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    POSTMORTEM_DONE = "postmortem_done"


class CostSource(str, Enum):
    """Where a cost sample came from."""

    AI = "ai"  # Anthropic / OpenAI
    INFRA = "infra"  # cloud
    SAAS = "saas"  # third-party services
    OTHER = "other"
