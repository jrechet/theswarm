"""Entities for autonomy-spectrum config (Phase L)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.autonomy_config.value_objects import AutonomyLevel


@dataclass(frozen=True)
class AutonomyConfig:
    """Per-(project, role) autonomy setting."""

    id: str
    project_id: str
    role: str
    level: AutonomyLevel = AutonomyLevel.SUPERVISED
    note: str = ""
    updated_by: str = ""
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def gate_label(self) -> str:
        """Human-friendly label describing the gating behaviour."""
        return {
            AutonomyLevel.MANUAL: "human-initiated",
            AutonomyLevel.ASSISTED: "confirm every step",
            AutonomyLevel.SUPERVISED: "review before merge",
            AutonomyLevel.AUTONOMOUS: "ship unless blocked",
        }[self.level]
