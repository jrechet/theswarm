"""Query: assemble dashboard state from multiple sources."""

from __future__ import annotations

from theswarm.application.dto import CycleDTO, DashboardDTO, PhaseDTO, ProjectDTO
from theswarm.domain.cycles.ports import CycleRepository
from theswarm.domain.cycles.value_objects import CycleStatus
from theswarm.domain.projects.ports import ProjectRepository


class GetDashboardQuery:
    def __init__(
        self,
        project_repo: ProjectRepository,
        cycle_repo: CycleRepository,
    ) -> None:
        self._project_repo = project_repo
        self._cycle_repo = cycle_repo

    async def execute(self) -> DashboardDTO:
        projects = await self._project_repo.list_all()

        project_dtos = [
            ProjectDTO(
                id=p.id,
                repo=str(p.repo),
                default_branch=p.default_branch,
                framework=p.framework.value,
                ticket_source=p.ticket_source.value,
                team_channel=p.team_channel,
                schedule=p.schedule,
                test_command=p.test_command,
                source_dir=p.source_dir,
                max_daily_stories=p.config.max_daily_stories,
                created_at=p.created_at.isoformat(),
            )
            for p in projects
        ]

        active_cycles: list[CycleDTO] = []
        total_cost = 0.0

        for p in projects:
            cycles = await self._cycle_repo.list_by_project(p.id, limit=5)
            for c in cycles:
                if c.status == CycleStatus.RUNNING:
                    active_cycles.append(
                        CycleDTO(
                            id=str(c.id),
                            project_id=c.project_id,
                            status=c.status.value,
                            triggered_by=c.triggered_by,
                            started_at=c.started_at.isoformat() if c.started_at else None,
                            completed_at=None,
                            total_tokens=c.total_tokens,
                            total_cost_usd=c.total_cost_usd,
                            prs_opened=list(c.prs_opened),
                            prs_merged=list(c.prs_merged),
                            phases=[
                                PhaseDTO(
                                    phase=ph.phase,
                                    agent=ph.agent,
                                    status=ph.status.value,
                                    started_at=ph.started_at.isoformat(),
                                    completed_at=ph.completed_at.isoformat() if ph.completed_at else None,
                                    tokens_used=ph.tokens_used,
                                    cost_usd=ph.cost_usd,
                                    summary=ph.summary,
                                )
                                for ph in c.phases
                            ],
                        )
                    )
                total_cost += c.total_cost_usd

        return DashboardDTO(
            active_cycles=active_cycles,
            recent_activities=[],
            projects=project_dtos,
            total_cost_today=total_cost,
        )
