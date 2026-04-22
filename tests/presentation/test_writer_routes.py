"""Phase J presentation tests for Writer routes."""

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
    conn = await init_db(str(tmp_path / "writer_routes.db"))
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


class TestDocRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/writer/docs")
        assert r.status_code == 200
        assert "No docs tracked yet." in r.text

    async def test_upsert_and_mark_ready(self, client):
        r = await client.post(
            "/projects/demo/writer/docs",
            data={
                "path": "README.md",
                "kind": "readme",
                "title": "TheSwarm",
                "summary": "autonomous dev team",
                "status": "draft",
            },
        )
        assert r.status_code == 200
        assert "README.md" in r.text
        assert "draft" in r.text

        r = await client.post(
            "/projects/demo/writer/docs/status",
            data={"path": "README.md", "status": "ready"},
        )
        assert r.status_code == 200
        assert "ready" in r.text

    async def test_stale_shows_refresh_badge(self, client):
        await client.post(
            "/projects/demo/writer/docs",
            data={"path": "README.md", "status": "stale"},
        )
        r = await client.get("/projects/demo/writer/docs")
        assert r.status_code == 200
        assert "stale" in r.text
        assert "needs refresh" in r.text

    async def test_unknown_kind_falls_back(self, client):
        r = await client.post(
            "/projects/demo/writer/docs",
            data={"path": "CHANGELOG.md", "kind": "bogus"},
        )
        assert r.status_code == 200
        assert "CHANGELOG.md" in r.text
        assert "readme" in r.text

    async def test_unknown_status_400(self, client):
        await client.post(
            "/projects/demo/writer/docs", data={"path": "a.md"},
        )
        r = await client.post(
            "/projects/demo/writer/docs/status",
            data={"path": "a.md", "status": "bogus"},
        )
        assert r.status_code == 400


class TestQuickstartRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/writer/quickstart")
        assert r.status_code == 200
        assert "No quickstart checks yet." in r.text

    async def test_record_fail(self, client):
        r = await client.post(
            "/projects/demo/writer/quickstart",
            data={
                "step_count": 5,
                "duration_seconds": 10.5,
                "outcome": "fail",
                "failure_step": "step 3: uv sync",
                "note": "missing ANTHROPIC_API_KEY",
            },
        )
        assert r.status_code == 200
        assert "fail" in r.text
        assert "step 3: uv sync" in r.text
        assert "missing ANTHROPIC_API_KEY" in r.text

    async def test_unknown_outcome_falls_back(self, client):
        r = await client.post(
            "/projects/demo/writer/quickstart",
            data={"outcome": "bogus"},
        )
        assert r.status_code == 200
        assert "skipped" in r.text


class TestChangelogRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/writer/changelog")
        assert r.status_code == 200
        assert "No changelog entries yet." in r.text

    async def test_record_breaking(self, client):
        r = await client.post(
            "/projects/demo/writer/changelog",
            data={
                "kind": "breaking",
                "summary": "drop legacy endpoint",
                "pr_url": "https://github.com/x/y/pull/123",
            },
        )
        assert r.status_code == 200
        assert "drop legacy endpoint" in r.text
        assert "BREAKING" in r.text
        assert "unreleased" in r.text

    async def test_version_bundled(self, client):
        r = await client.post(
            "/projects/demo/writer/changelog",
            data={
                "kind": "feat",
                "summary": "add cycles",
                "version": "1.0.0",
            },
        )
        assert r.status_code == 200
        assert "v1.0.0" in r.text

    async def test_unknown_kind_falls_back(self, client):
        r = await client.post(
            "/projects/demo/writer/changelog",
            data={"kind": "bogus", "summary": "x"},
        )
        assert r.status_code == 200
        assert "chore" in r.text
