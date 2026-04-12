"""Query: get a single project by ID."""

from __future__ import annotations

from theswarm.application.dto import ProjectDTO
from theswarm.domain.projects.ports import ProjectRepository


class GetProjectQuery:
    def __init__(self, project_repo: ProjectRepository) -> None:
        self._project_repo = project_repo

    async def execute(self, project_id: str) -> ProjectDTO | None:
        p = await self._project_repo.get(project_id)
        if p is None:
            return None
        return ProjectDTO(
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
