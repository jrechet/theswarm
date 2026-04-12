"""Query: get cycle status and details."""

from __future__ import annotations

from theswarm.application.dto import CycleDTO, PhaseDTO
from theswarm.domain.cycles.ports import CycleRepository
from theswarm.domain.cycles.value_objects import CycleId


class GetCycleStatusQuery:
    def __init__(self, cycle_repo: CycleRepository) -> None:
        self._cycle_repo = cycle_repo

    async def execute(self, cycle_id: str) -> CycleDTO | None:
        cycle = await self._cycle_repo.get(CycleId(cycle_id))
        if cycle is None:
            return None
        return CycleDTO(
            id=str(cycle.id),
            project_id=cycle.project_id,
            status=cycle.status.value,
            triggered_by=cycle.triggered_by,
            started_at=cycle.started_at.isoformat() if cycle.started_at else None,
            completed_at=cycle.completed_at.isoformat() if cycle.completed_at else None,
            total_tokens=cycle.total_tokens,
            total_cost_usd=cycle.total_cost_usd,
            prs_opened=list(cycle.prs_opened),
            prs_merged=list(cycle.prs_merged),
            phases=[
                PhaseDTO(
                    phase=p.phase,
                    agent=p.agent,
                    status=p.status.value,
                    started_at=p.started_at.isoformat(),
                    completed_at=p.completed_at.isoformat() if p.completed_at else None,
                    tokens_used=p.tokens_used,
                    cost_usd=p.cost_usd,
                    summary=p.summary,
                )
                for p in cycle.phases
            ],
        )
