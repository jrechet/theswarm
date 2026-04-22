"""Phase L presentation tests — prompt library routes."""

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
    conn = await init_db(str(tmp_path / "prompt_routes.db"))
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


class TestPromptLibraryRoutes:
    async def test_list_empty(self, client):
        r = await client.get("/prompt-library")
        assert r.status_code == 200
        assert "No prompt templates yet." in r.text

    async def test_upsert_shows_template(self, client):
        r = await client.post(
            "/prompt-library",
            data={
                "name": "po.morning_plan", "role": "po",
                "body": "plan the day", "actor": "alice",
                "note": "initial",
            },
        )
        assert r.status_code == 200
        assert "po.morning_plan" in r.text
        assert "v1" in r.text
        assert "active" in r.text

    async def test_update_bumps_version(self, client):
        await client.post(
            "/prompt-library",
            data={"name": "x", "body": "a"},
        )
        r = await client.post(
            "/prompt-library",
            data={"name": "x", "body": "b"},
        )
        assert r.status_code == 200
        assert "v2" in r.text

    async def test_deprecate_flips_state(self, client):
        await client.post("/prompt-library", data={"name": "x"})
        r = await client.post(
            "/prompt-library/x/deprecate",
            data={"actor": "alice", "note": "stale"},
        )
        assert r.status_code == 200
        assert "deprecated" in r.text

    async def test_restore_reactivates(self, client):
        await client.post("/prompt-library", data={"name": "x"})
        await client.post("/prompt-library/x/deprecate", data={})
        r = await client.post("/prompt-library/x/restore", data={})
        assert r.status_code == 200
        assert "Restore" not in r.text or "active" in r.text

    async def test_deprecate_missing_returns_404(self, client):
        r = await client.post("/prompt-library/missing/deprecate", data={})
        assert r.status_code == 404

    async def test_restore_missing_returns_404(self, client):
        r = await client.post("/prompt-library/missing/restore", data={})
        assert r.status_code == 404

    async def test_audit_lists_entries(self, client):
        await client.post(
            "/prompt-library",
            data={"name": "x", "body": "a", "actor": "alice", "note": "init"},
        )
        await client.post(
            "/prompt-library",
            data={"name": "x", "body": "b", "actor": "bob", "note": "tune"},
        )
        r = await client.get("/prompt-library/audit", params={"name": "x"})
        assert r.status_code == 200
        assert "x" in r.text
        assert "create" in r.text
        assert "update" in r.text

    async def test_audit_all_prompts(self, client):
        await client.post("/prompt-library", data={"name": "a"})
        await client.post("/prompt-library", data={"name": "b"})
        r = await client.get("/prompt-library/audit")
        assert r.status_code == 200
        assert "all prompts" in r.text
