"""The preview URL template persists through its command (from V1's live-preview tests, M6)."""

from __future__ import annotations

import pytest
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteProjectRepository, init_db


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "live.db"))
    yield conn
    await conn.close()


async def test_preview_url_template_persisted_through_command(db):
    from theswarm.application.commands.update_project_config import (
        UpdateProjectConfigCommand,
        UpdateProjectConfigHandler,
    )

    project_repo = SQLiteProjectRepository(db)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))

    handler = UpdateProjectConfigHandler(project_repo)
    await handler.handle(
        UpdateProjectConfigCommand(
            project_id="alpha",
            preview_url_template="https://preview.example/{branch}",
        ),
    )

    loaded = await project_repo.get("alpha")
    assert loaded is not None
    assert loaded.config.preview_url_template == "https://preview.example/{branch}"
