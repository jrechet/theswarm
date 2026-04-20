"""Tests for Sprint B C1 — UpdateProjectConfigHandler."""

from __future__ import annotations

import pytest

from theswarm.application.commands.update_project_config import (
    ProjectNotFound,
    UpdateProjectConfigCommand,
    UpdateProjectConfigHandler,
)
from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.value_objects import RepoUrl


class _InMemProjectRepo:
    def __init__(self, project: Project | None = None) -> None:
        self._projects: dict[str, Project] = {}
        if project is not None:
            self._projects[project.id] = project

    async def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    async def save(self, project: Project) -> None:
        self._projects[project.id] = project

    async def list_all(self) -> list[Project]:
        return list(self._projects.values())

    async def delete(self, project_id: str) -> None:
        self._projects.pop(project_id, None)


def _make_project() -> Project:
    return Project(id="p", repo=RepoUrl("o/r"))


class TestUpdateProjectConfigHandler:
    async def test_missing_project_raises(self):
        repo = _InMemProjectRepo()
        handler = UpdateProjectConfigHandler(repo)
        with pytest.raises(ProjectNotFound):
            await handler.handle(UpdateProjectConfigCommand(project_id="nope"))

    async def test_partial_update_keeps_other_fields(self):
        repo = _InMemProjectRepo(_make_project())
        handler = UpdateProjectConfigHandler(repo)
        cfg = await handler.handle(
            UpdateProjectConfigCommand(project_id="p", effort="high"),
        )
        assert cfg.effort == "high"
        # Defaults preserved
        assert cfg.max_daily_stories == 3
        assert cfg.paused is False

    async def test_models_merge_not_replace(self):
        repo = _InMemProjectRepo(_make_project())
        handler = UpdateProjectConfigHandler(repo)
        cfg = await handler.handle(
            UpdateProjectConfigCommand(project_id="p", models={"dev": "opus"}),
        )
        assert cfg.models["dev"] == "opus"
        # Other phases retain defaults
        assert cfg.models["po"] == "sonnet"
        assert cfg.models["qa"] == "haiku"

    async def test_unknown_phase_rejected(self):
        repo = _InMemProjectRepo(_make_project())
        handler = UpdateProjectConfigHandler(repo)
        with pytest.raises(ValueError, match="unknown model phases"):
            await handler.handle(
                UpdateProjectConfigCommand(project_id="p", models={"hacker": "opus"}),
            )

    async def test_empty_model_value_rejected(self):
        repo = _InMemProjectRepo(_make_project())
        handler = UpdateProjectConfigHandler(repo)
        with pytest.raises(ValueError, match="non-empty string"):
            await handler.handle(
                UpdateProjectConfigCommand(project_id="p", models={"dev": ""}),
            )

    async def test_pause_round_trip(self):
        repo = _InMemProjectRepo(_make_project())
        handler = UpdateProjectConfigHandler(repo)
        paused = await handler.handle(
            UpdateProjectConfigCommand(project_id="p", paused=True),
        )
        assert paused.paused is True
        resumed = await handler.handle(
            UpdateProjectConfigCommand(project_id="p", paused=False),
        )
        assert resumed.paused is False

    async def test_caps_stored(self):
        repo = _InMemProjectRepo(_make_project())
        handler = UpdateProjectConfigHandler(repo)
        cfg = await handler.handle(
            UpdateProjectConfigCommand(
                project_id="p",
                daily_cost_cap_usd=25.0,
                daily_tokens_cap=100_000,
                monthly_cost_cap_usd=500.0,
            ),
        )
        assert cfg.daily_cost_cap_usd == 25.0
        assert cfg.daily_tokens_cap == 100_000
        assert cfg.monthly_cost_cap_usd == 500.0

    async def test_negative_max_daily_rejected(self):
        repo = _InMemProjectRepo(_make_project())
        handler = UpdateProjectConfigHandler(repo)
        with pytest.raises(ValueError, match="max_daily_stories"):
            await handler.handle(
                UpdateProjectConfigCommand(project_id="p", max_daily_stories=-1),
            )
