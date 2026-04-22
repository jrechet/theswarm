"""Command: register a new project."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from theswarm.application.services.role_assignment_service import RoleAssignmentService
from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.ports import ProjectRepository
from theswarm.domain.projects.value_objects import Framework, RepoUrl, TicketSourceType

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateProjectCommand:
    project_id: str
    repo: str
    framework: str = "auto"
    ticket_source: str = "github"
    team_channel: str = ""
    max_daily_stories: int = 3


class CreateProjectHandler:
    def __init__(
        self,
        project_repo: ProjectRepository,
        role_service: RoleAssignmentService | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._role_service = role_service

    async def handle(self, cmd: CreateProjectCommand) -> Project:
        existing = await self._project_repo.get(cmd.project_id)
        if existing is not None:
            raise ValueError(f"Project already exists: {cmd.project_id}")

        framework = Framework(cmd.framework) if cmd.framework != "auto" else Framework.AUTO
        ticket_source = TicketSourceType(cmd.ticket_source)

        project = Project(
            id=cmd.project_id,
            repo=RepoUrl(cmd.repo),
            framework=framework,
            ticket_source=ticket_source,
            team_channel=cmd.team_channel,
            config=ProjectConfig(max_daily_stories=cmd.max_daily_stories),
        )
        await self._project_repo.save(project)

        if self._role_service is not None:
            try:
                await self._role_service.assign_core_roster(project.id)
            except Exception:
                log.exception(
                    "Failed to assign core roster for project %s",
                    project.id,
                )
        return project
