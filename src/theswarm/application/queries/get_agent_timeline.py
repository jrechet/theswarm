"""Query: agent timeline per cycle — latest activity per agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AgentTimelineRow:
    agent: str
    phase: str
    last_action: str
    last_detail: str
    last_event_at: datetime | None
    activity_count: int


class GetAgentTimelineQuery:
    """Build per-agent timeline rows from the activities store."""

    AGENTS: tuple[str, ...] = ("po", "techlead", "dev", "qa")

    def __init__(self, activity_repo: object | None) -> None:
        self._activity_repo = activity_repo

    async def execute(self, cycle_id: str) -> list[AgentTimelineRow]:
        if self._activity_repo is None:
            return [
                AgentTimelineRow(a, "", "", "", None, 0) for a in self.AGENTS
            ]

        activities = await self._activity_repo.list_by_cycle(cycle_id, limit=500)

        by_agent: dict[str, list[dict]] = {a: [] for a in self.AGENTS}
        for row in activities:
            agent = row.get("agent", "")
            by_agent.setdefault(agent, []).append(row)

        rows: list[AgentTimelineRow] = []
        for agent in self.AGENTS:
            items = by_agent.get(agent, [])
            items_sorted = sorted(
                items, key=lambda r: r.get("created_at", ""), reverse=True,
            )
            latest = items_sorted[0] if items_sorted else None
            last_at: datetime | None = None
            if latest and latest.get("created_at"):
                try:
                    last_at = datetime.fromisoformat(latest["created_at"])
                except (TypeError, ValueError):
                    last_at = None
            rows.append(
                AgentTimelineRow(
                    agent=agent,
                    phase=(latest.get("action") if latest else "") or "",
                    last_action=(latest.get("action") if latest else "") or "",
                    last_detail=(latest.get("detail") if latest else "") or "",
                    last_event_at=last_at,
                    activity_count=len(items),
                ),
            )
        return rows
