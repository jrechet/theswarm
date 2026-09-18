"""`/health` `repos` must list registered projects alongside env repos (#148)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.routes import health as health_routes


def _app(project_repo, vcs_map) -> FastAPI:
    app = FastAPI()
    app.include_router(health_routes.router)
    app.state.project_repo = project_repo
    app.state.sse_hub = object()
    app.state.gateway_bridge = SimpleNamespace(
        _swarm_po_vcs_map=vcs_map, _swarm_po_github=object(), _swarm_po_chat=object(),
    )
    return app


async def test_health_repos_includes_registered_projects(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    project_repo = SQLiteProjectRepository(conn)

    from theswarm.application.commands.create_project import (
        CreateProjectCommand,
        CreateProjectHandler,
    )

    await CreateProjectHandler(project_repo).handle(
        CreateProjectCommand(project_id="yakoi", repo="jrechet/yakoi"),
    )

    app = _app(project_repo, {"jrechet/theswarm": object()})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    repos = resp.json()["repos"]
    assert "jrechet/theswarm" in repos
    assert "jrechet/yakoi" in repos
    await conn.close()
