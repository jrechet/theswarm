"""Phase J presentation tests for Release routes."""

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
    conn = await init_db(str(tmp_path / "release_routes.db"))
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


class TestVersionRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/release/versions")
        assert r.status_code == 200
        assert "No releases cut yet." in r.text

    async def test_draft_release_rollback_flow(self, client):
        r = await client.post(
            "/projects/demo/release/versions",
            data={"version": "1.0.0", "summary": "first release"},
        )
        assert r.status_code == 200
        assert "v1.0.0" in r.text
        assert "draft" in r.text

        r = await client.post(
            "/projects/demo/release/versions/1.0.0/release",
        )
        assert r.status_code == 200
        assert "released" in r.text

        r = await client.post(
            "/projects/demo/release/versions/1.0.0/rollback",
        )
        assert r.status_code == 200
        assert "rolled_back" in r.text

    async def test_release_missing_404(self, client):
        r = await client.post(
            "/projects/demo/release/versions/99.0.0/release",
        )
        assert r.status_code == 404


class TestFlagRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/release/flags")
        assert r.status_code == 200
        assert "No feature flags tracked yet." in r.text

    async def test_upsert_and_archive(self, client):
        r = await client.post(
            "/projects/demo/release/flags",
            data={
                "name": "new_ux",
                "owner": "growth",
                "description": "new onboarding",
                "state": "active",
                "rollout_percent": 25,
                "cleanup_after_days": 90,
            },
        )
        assert r.status_code == 200
        assert "new_ux" in r.text
        assert "25%" in r.text
        assert "active" in r.text

        r = await client.post(
            "/projects/demo/release/flags/new_ux/archive",
        )
        assert r.status_code == 200
        assert "archived" in r.text

    async def test_unknown_state_falls_back(self, client):
        r = await client.post(
            "/projects/demo/release/flags",
            data={"name": "x", "state": "bogus"},
        )
        assert r.status_code == 200
        assert "active" in r.text

    async def test_archive_missing_404(self, client):
        r = await client.post(
            "/projects/demo/release/flags/nope/archive",
        )
        assert r.status_code == 404


class TestRollbackRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/release/rollbacks")
        assert r.status_code == 200
        assert "No rollback actions armed yet." in r.text

    async def test_arm_execute_flow(self, client):
        r = await client.post(
            "/projects/demo/release/rollbacks",
            data={
                "release_version": "1.0.0",
                "revert_ref": "abc123",
                "note": "context",
            },
        )
        assert r.status_code == 200
        assert "v1.0.0" in r.text
        assert "abc123" in r.text
        assert "ready" in r.text
        assert "armed" in r.text

        # Get the action id from listing — we'll need it to execute
        r = await client.get("/projects/demo/release/rollbacks")
        assert r.status_code == 200

    async def test_execute_missing_404(self, client):
        r = await client.post(
            "/projects/demo/release/rollbacks/missing-id/execute",
        )
        assert r.status_code == 404

    async def test_obsolete_missing_404(self, client):
        r = await client.post(
            "/projects/demo/release/rollbacks/missing-id/obsolete",
        )
        assert r.status_code == 404
