"""Ports (interfaces) for the Projects bounded context."""

from __future__ import annotations

from typing import Protocol

from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import FrameworkInfo


class ProjectRepository(Protocol):
    """Persistence port for projects."""

    async def get(self, project_id: str) -> Project | None: ...
    async def list_all(self) -> list[Project]: ...
    async def save(self, project: Project) -> None: ...
    async def delete(self, project_id: str) -> None: ...


class FrameworkDetector(Protocol):
    """Detects project framework from workspace files."""

    async def detect(self, workspace_path: str) -> FrameworkInfo: ...
