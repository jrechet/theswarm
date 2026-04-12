"""Query: list cycles for a project."""

from __future__ import annotations

from theswarm.application.dto import CycleDTO, PhaseDTO
from theswarm.domain.cycles.ports import CycleRepository


class ListCyclesQuery:
    def __init__(self, cycle_repo: CycleRepository) -> None:
        self._cycle_repo = cycle_repo

    async def execute(self, project_id: str, limit: int = 30) -> list[CycleDTO]:
        cycles = await self._cycle_repo.list_by_project(project_id, limit=limit)
        return [
            CycleDTO(
                id=str(c.id),
                project_id=c.project_id,
                status=c.status.value,
                triggered_by=c.triggered_by,
                started_at=c.started_at.isoformat() if c.started_at else None,
                completed_at=c.completed_at.isoformat() if c.completed_at else None,
                total_tokens=c.total_tokens,
                total_cost_usd=c.total_cost_usd,
                prs_opened=list(c.prs_opened),
                prs_merged=list(c.prs_merged),
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
                    for p in c.phases
                ],
            )
            for c in cycles
        ]
