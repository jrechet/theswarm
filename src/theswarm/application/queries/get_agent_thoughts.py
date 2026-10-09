"""Query for agent thoughts and steps (Sprint D V3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ThoughtEntry:
    kind: str  # "thought" | "step"
    agent: str
    text: str
    detail: str
    phase: str
    occurred_at: datetime
    metadata: dict = field(default_factory=dict)  # an AgentActivity's, for the stations


class GetAgentThoughtsQuery:
    """Return agent thoughts/steps from the cycle event store, in order."""

    def __init__(self, cycle_event_store: object | None) -> None:
        self._store = cycle_event_store

    async def execute(self, cycle_id: str, *, include_activity: bool = False) -> list[ThoughtEntry]:
        """Thoughts and steps; with `include_activity`, what the agents said
        through the ProgressBridge too (`AgentActivity`, kind = its action).

        Nothing has emitted AgentThought/AgentStep since the pipeline moved
        to the bridge: the V2 theater's feed read only those and said
        "Nothing yet" to the end of cycle 28371c2016da, over 197 stored
        activity events.
        """
        if self._store is None:
            return []
        records = await self._store.list_for_cycle(cycle_id)
        entries: list[ThoughtEntry] = []
        for r in records:
            if include_activity and r.event_type == "AgentActivity":
                entries.append(
                    ThoughtEntry(
                        kind=str(r.payload.get("action", "progress")),
                        agent=str(r.payload.get("agent", "")),
                        text=str(r.payload.get("detail", "")),
                        detail="",
                        phase="",
                        occurred_at=r.occurred_at,
                        metadata=dict(r.payload.get("metadata") or {}),
                    ),
                )
                continue
            if r.event_type == "AgentThought":
                entries.append(
                    ThoughtEntry(
                        kind="thought",
                        agent=str(r.payload.get("agent", "")),
                        text=str(r.payload.get("thought", "")),
                        detail="",
                        phase=str(r.payload.get("phase", "")),
                        occurred_at=r.occurred_at,
                    ),
                )
            elif r.event_type == "AgentStep":
                entries.append(
                    ThoughtEntry(
                        kind="step",
                        agent=str(r.payload.get("agent", "")),
                        text=str(r.payload.get("step", "")),
                        detail=str(r.payload.get("detail", "")),
                        phase=str(r.payload.get("phase", "")),
                        occurred_at=r.occurred_at,
                    ),
                )
        return entries
