"""Value objects for autonomy-spectrum config (Phase L)."""

from __future__ import annotations

from enum import Enum


class AutonomyLevel(str, Enum):
    """How independently an agent can act for a given project."""

    MANUAL = "manual"            # human-initiated only
    ASSISTED = "assisted"        # agent proposes, human confirms every step
    SUPERVISED = "supervised"    # agent acts, human reviews before merge
    AUTONOMOUS = "autonomous"    # agent acts and ships unless blocked

    @property
    def rank(self) -> int:
        order = {
            AutonomyLevel.MANUAL: 0,
            AutonomyLevel.ASSISTED: 1,
            AutonomyLevel.SUPERVISED: 2,
            AutonomyLevel.AUTONOMOUS: 3,
        }
        return order[self]

    @property
    def requires_human_before_action(self) -> bool:
        return self in (AutonomyLevel.MANUAL, AutonomyLevel.ASSISTED)
