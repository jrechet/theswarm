"""Command: remove a project."""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.projects.ports import ProjectRepository


@dataclass(frozen=True)
class DeleteProjectCommand:
    project_id: str


class DeleteProjectHandler:
    def __init__(self, project_repo: ProjectRepository) -> None:
        self._project_repo = project_repo

    async def handle(self, cmd: DeleteProjectCommand) -> None:
        existing = await self._project_repo.get(cmd.project_id)
        if existing is None:
            raise ValueError(f"Project not found: {cmd.project_id}")
        await self._project_repo.delete(cmd.project_id)
