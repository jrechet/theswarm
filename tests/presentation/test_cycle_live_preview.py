"""Sprint C F9 — Live preview iframe during cycle."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "live.db"))
    yield conn
    await conn.close()


async def _mk_app(db, project: Project, cycle: Cycle | None = None):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    await project_repo.save(project)
    if cycle is not None:
        await cycle_repo.save(cycle)
    return create_web_app(project_repo, cycle_repo, EventBus(), SSEHub())


async def test_live_preview_renders_iframe_when_template_and_pr_set(db):
    project = Project(
        id="alpha",
        repo=RepoUrl("o/alpha"),
        config=ProjectConfig(preview_url_template="https://preview.example/{pr}"),
    )
    cycle = Cycle(
        id=CycleId("cyc-1"),
        project_id="alpha",
        status=CycleStatus.RUNNING,
        started_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        prs_opened=(42,),
    )
    app = await _mk_app(db, project, cycle)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/cycles/cyc-1/live")

    assert r.status_code == 200
    assert "<iframe" in r.text
    assert 'src="https://preview.example/42"' in r.text
    assert 'sandbox="allow-scripts allow-same-origin allow-forms"' in r.text


async def test_live_preview_shows_empty_when_template_missing(db):
    project = Project(id="alpha", repo=RepoUrl("o/alpha"))
    cycle = Cycle(
        id=CycleId("cyc-1"),
        project_id="alpha",
        status=CycleStatus.RUNNING,
        started_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        prs_opened=(42,),
    )
    app = await _mk_app(db, project, cycle)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/cycles/cyc-1/live")

    assert r.status_code == 200
    assert "<iframe" not in r.text
    assert "No preview URL template configured" in r.text


async def test_live_preview_shows_empty_when_no_pr_yet(db):
    project = Project(
        id="alpha",
        repo=RepoUrl("o/alpha"),
        config=ProjectConfig(preview_url_template="https://preview.example/{pr}"),
    )
    cycle = Cycle(
        id=CycleId("cyc-1"),
        project_id="alpha",
        status=CycleStatus.RUNNING,
        started_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    app = await _mk_app(db, project, cycle)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/cycles/cyc-1/live")

    assert r.status_code == 200
    assert "<iframe" not in r.text
    assert "No open PR yet" in r.text


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
