"""Sprint E M2 — end-of-cycle retrospective service.

Each agent that ran during the cycle contributes 1–3 structured learnings:
- warnings on failed phases
- lessons when budget pressure / cost spikes happened
- conventions on healthy, clean phases

Learnings are persisted to the MemoryStore so future runs of the same agent
can replay them, and returned as plain strings for ``DemoReport.agent_learnings``
to surface on the demo player's learnings slide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import PhaseStatus
from theswarm.domain.memory.entities import MemoryEntry, Retrospective
from theswarm.domain.memory.ports import MemoryStore
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope

log = logging.getLogger(__name__)

_BUDGET_PRESSURE_RATIO = 0.9
_HIGH_COST_USD = 2.0


@dataclass(frozen=True)
class RetrospectiveResult:
    retrospective: Retrospective
    learnings: tuple[str, ...]


class RetrospectiveService:
    """Collect per-agent learnings from a cycle and persist them."""

    def __init__(self, memory_store: MemoryStore) -> None:
        self._store = memory_store

    async def run(self, cycle: Cycle) -> RetrospectiveResult:
        """Build learnings for every agent that participated, persist, return."""
        entries = self.collect(cycle)
        if entries:
            await self._store.append(list(entries))
        retrospective = Retrospective(
            cycle_date=(cycle.started_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d"),
            project_id=cycle.project_id,
            entries=entries,
        )
        return RetrospectiveResult(
            retrospective=retrospective,
            learnings=tuple(e.content for e in entries),
        )

    def collect(self, cycle: Cycle) -> tuple[MemoryEntry, ...]:
        """Pure collection — no side effects, useful for tests + previews."""
        cycle_date = (cycle.started_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        budget_by_role = {b.role: b for b in cycle.budgets}
        agents_seen: set[str] = set()
        entries: list[MemoryEntry] = []

        for phase in cycle.phases:
            agent = (phase.agent or "").strip()
            if not agent:
                continue
            agents_seen.add(agent)
            for e in self._learnings_for_phase(
                phase, cycle, budget_by_role.get(agent), cycle_date,
            ):
                entries.append(e)

        # Cap 1-3 per agent, preserve order
        capped: list[MemoryEntry] = []
        counts: dict[str, int] = {}
        for e in entries:
            n = counts.get(e.agent, 0)
            if n >= 3:
                continue
            counts[e.agent] = n + 1
            capped.append(e)

        # Every agent that ran must contribute at least one learning.
        for agent in agents_seen:
            if counts.get(agent, 0) == 0:
                capped.append(
                    self._entry(
                        cycle=cycle,
                        agent=agent,
                        category=MemoryCategory.CONVENTIONS,
                        content=f"{agent}: cycle ran without notable incident.",
                        cycle_date=cycle_date,
                    )
                )

        return tuple(capped)

    def _learnings_for_phase(
        self,
        phase: PhaseExecution,
        cycle: Cycle,
        budget,
        cycle_date: str,
    ) -> list[MemoryEntry]:
        out: list[MemoryEntry] = []
        agent = phase.agent or "unknown"

        if phase.status == PhaseStatus.FAILED:
            summary = phase.summary or "no summary available"
            out.append(self._entry(
                cycle=cycle, agent=agent,
                category=MemoryCategory.ERRORS,
                content=f"{agent}: phase '{phase.phase}' failed — {summary}",
                cycle_date=cycle_date,
            ))

        if budget is not None and budget.limit > 0:
            ratio = phase.tokens_used / budget.limit
            if ratio >= _BUDGET_PRESSURE_RATIO:
                out.append(self._entry(
                    cycle=cycle, agent=agent,
                    category=MemoryCategory.IMPROVEMENTS,
                    content=(
                        f"{agent}: used {phase.tokens_used:,} / {budget.limit:,} tokens "
                        f"({ratio*100:.0f}%) on '{phase.phase}' — tighten prompts or raise budget."
                    ),
                    cycle_date=cycle_date,
                ))

        if phase.cost_usd >= _HIGH_COST_USD:
            out.append(self._entry(
                cycle=cycle, agent=agent,
                category=MemoryCategory.IMPROVEMENTS,
                content=(
                    f"{agent}: phase '{phase.phase}' cost ${phase.cost_usd:.2f} — "
                    "consider a cheaper model for this phase."
                ),
                cycle_date=cycle_date,
            ))

        if (
            phase.status == PhaseStatus.COMPLETED
            and not out
            and phase.tokens_used > 0
        ):
            out.append(self._entry(
                cycle=cycle, agent=agent,
                category=MemoryCategory.CONVENTIONS,
                content=(
                    f"{agent}: '{phase.phase}' completed cleanly at "
                    f"{phase.tokens_used:,} tokens / ${phase.cost_usd:.2f}."
                ),
                cycle_date=cycle_date,
            ))

        return out

    @staticmethod
    def _entry(
        *,
        cycle: Cycle,
        agent: str,
        category: MemoryCategory,
        content: str,
        cycle_date: str,
    ) -> MemoryEntry:
        return MemoryEntry(
            category=category,
            content=content,
            agent=agent,
            scope=ProjectScope(project_id=cycle.project_id),
            cycle_date=cycle_date,
            created_at=datetime.now(timezone.utc),
        )
