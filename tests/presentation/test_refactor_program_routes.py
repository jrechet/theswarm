"""Phase L presentation tests — refactor program routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "refactor_routes.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def app(db):
    return create_web_app(
        SQLiteProjectRepository(db), SQLiteCycleRepository(db),
        EventBus(), SSEHub(), db=db,
    )


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestRefactorProgramRoutes:
    async def test_empty(self, client):
        r = await client.get("/refactor-programs")
        assert r.status_code == 200
        assert "No refactor programs yet." in r.text

    async def test_upsert_creates_program(self, client):
        r = await client.post(
            "/refactor-programs",
            data={
                "title": "Migrate to v2 auth",
                "rationale": "legal requires session token rotation",
                "target_projects": "proj-a\nproj-b",
                "owner": "@Ada",
                "status": "proposed",
            },
        )
        assert r.status_code == 200
        assert "Migrate to v2 auth" in r.text
        assert "legal requires" in r.text
        assert "proj-a" in r.text
        assert "proj-b" in r.text
        assert "2 project(s)" in r.text
        assert "proposed" in r.text

    async def test_unknown_status_falls_back(self, client):
        r = await client.post(
            "/refactor-programs",
            data={"title": "t", "status": "bogus"},
        )
        assert r.status_code == 200
        assert "proposed" in r.text

    async def test_activate_flow(self, client):
        await client.post(
            "/refactor-programs",
            data={"title": "t", "target_projects": "a"},
        )
        r = await client.post(
            "/refactor-programs/activate", data={"title": "t"},
        )
        assert r.status_code == 200
        assert "active" in r.text

    async def test_activate_missing_404(self, client):
        r = await client.post(
            "/refactor-programs/activate", data={"title": "missing"},
        )
        assert r.status_code == 404

    async def test_complete_happy_path(self, client):
        await client.post("/refactor-programs", data={"title": "t"})
        await client.post(
            "/refactor-programs/activate", data={"title": "t"},
        )
        r = await client.post(
            "/refactor-programs/complete", data={"title": "t"},
        )
        assert r.status_code == 200
        assert "completed" in r.text

    async def test_cancel_happy_path(self, client):
        await client.post("/refactor-programs", data={"title": "t"})
        r = await client.post(
            "/refactor-programs/cancel", data={"title": "t"},
        )
        assert r.status_code == 200
        assert "cancelled" in r.text

    async def test_add_and_remove_project(self, client):
        await client.post(
            "/refactor-programs",
            data={"title": "t", "target_projects": "a"},
        )
        r = await client.post(
            "/refactor-programs/add-project",
            data={"title": "t", "project_id": "bravo"},
        )
        assert r.status_code == 200
        assert "bravo" in r.text
        assert "2 project(s)" in r.text

        r = await client.post(
            "/refactor-programs/remove-project",
            data={"title": "t", "project_id": "a"},
        )
        assert r.status_code == 200
        assert "1 project(s)" in r.text

    async def test_add_project_missing_404(self, client):
        r = await client.post(
            "/refactor-programs/add-project",
            data={"title": "missing", "project_id": "a"},
        )
        assert r.status_code == 404
