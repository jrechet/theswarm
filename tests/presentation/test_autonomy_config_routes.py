"""Phase L presentation tests — autonomy config routes."""

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
    conn = await init_db(str(tmp_path / "autonomy_routes.db"))
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


class TestAutonomyConfigRoutes:
    async def test_list_empty(self, client):
        r = await client.get("/projects/p1/autonomy")
        assert r.status_code == 200
        assert "No autonomy overrides" in r.text

    async def test_set_shows_config(self, client):
        r = await client.post(
            "/projects/p1/autonomy",
            data={
                "role": "dev", "level": "autonomous",
                "note": "trusted team",
                "actor": "alice",
            },
        )
        assert r.status_code == 200
        assert "dev" in r.text
        assert "autonomous" in r.text
        assert "ship unless blocked" in r.text

    async def test_set_invalid_level_returns_400(self, client):
        r = await client.post(
            "/projects/p1/autonomy",
            data={"role": "dev", "level": "godmode"},
        )
        assert r.status_code == 400

    async def test_second_set_overwrites(self, client):
        await client.post(
            "/projects/p1/autonomy",
            data={"role": "dev", "level": "manual"},
        )
        r = await client.post(
            "/projects/p1/autonomy",
            data={"role": "dev", "level": "supervised"},
        )
        assert r.status_code == 200
        assert "supervised" in r.text
        # only one row shown
        assert r.text.count('<strong>dev</strong>') == 1

    async def test_project_isolation(self, client):
        await client.post(
            "/projects/p1/autonomy",
            data={"role": "dev", "level": "autonomous"},
        )
        r = await client.get("/projects/p2/autonomy")
        assert r.status_code == 200
        assert "No autonomy overrides" in r.text
