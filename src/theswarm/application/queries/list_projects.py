"""Query: list all registered projects."""

from __future__ import annotations

from theswarm.application.dto import ProjectDTO
from theswarm.domain.projects.ports import ProjectRepository


class ListProjectsQuery:
    def __init__(self, project_repo: ProjectRepository) -> None:
        self._project_repo = project_repo

    async def execute(self) -> list[ProjectDTO]:
        projects = await self._project_repo.list_all()
        return [
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
                effort=p.config.effort,
                models=dict(p.config.models),
                daily_cost_cap_usd=p.config.daily_cost_cap_usd,
                daily_tokens_cap=p.config.daily_tokens_cap,
                monthly_cost_cap_usd=p.config.monthly_cost_cap_usd,
                paused=p.config.paused,
            )
            for p in projects
        ]
