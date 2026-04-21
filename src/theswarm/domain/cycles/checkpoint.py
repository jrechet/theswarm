"""PhaseCheckpoint — Sprint G1 resilience primitive.

A PhaseCheckpoint captures the serialised state of a cycle just after a
phase completes (ok=True) or fails (ok=False). If the cycle crashes or is
killed mid-flight, the UI exposes a Resume action that re-runs from the
phase after the last ok=True checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


PHASE_ORDER: tuple[str, ...] = (
    "po_morning",
    "techlead_breakdown",
    "dev_loop",
    "qa",
    "po_evening",
)


@dataclass(frozen=True)
class PhaseCheckpoint:
    """A serialised cycle state captured after one phase."""

    cycle_id: str
    phase: str
    state_json: str
    ok: bool
    completed_at: datetime

    @property
    def next_phase(self) -> str | None:
        """Name of the phase that should run next, or None if we're past the end."""
        if self.phase not in PHASE_ORDER:
            return None
        idx = PHASE_ORDER.index(self.phase)
        if idx + 1 >= len(PHASE_ORDER):
            return None
        return PHASE_ORDER[idx + 1]
