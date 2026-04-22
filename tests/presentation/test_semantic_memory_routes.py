"""Phase L presentation tests — semantic memory routes."""

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
    conn = await init_db(str(tmp_path / "mem_routes.db"))
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


class TestSemanticMemoryRoutes:
    async def test_portfolio_empty(self, client):
        r = await client.get("/semantic-memory")
        assert r.status_code == 200
        assert "No memory entries yet." in r.text

    async def test_project_empty(self, client):
        r = await client.get("/projects/p1/semantic-memory")
        assert r.status_code == 200
        assert "No memory entries yet." in r.text

    async def test_record_portfolio(self, client):
        r = await client.post(
            "/semantic-memory",
            data={
                "title": "JWT rotation",
                "content": "rotate refresh tokens on every login",
                "tags": "auth, security",
                "source": "/docs/auth.md",
            },
        )
        assert r.status_code == 200
        assert "JWT rotation" in r.text
        assert "#auth" in r.text
        assert "#security" in r.text
        assert "portfolio" in r.text

    async def test_record_project_scoped(self, client):
        r = await client.post(
            "/projects/p1/semantic-memory",
            data={"title": "p1 note", "tags": "design"},
        )
        assert r.status_code == 200
        assert "p1 note" in r.text
        assert "p1" in r.text

    async def test_disable_toggle(self, client):
        r = await client.post(
            "/semantic-memory",
            data={"title": "to-disable", "tags": "x"},
        )
        import re
        ids = re.findall(
            r"/semantic-memory/([a-f0-9]+)/enable", r.text,
        )
        assert ids
        entry_id = ids[0]
        r = await client.post(
            f"/semantic-memory/{entry_id}/enable",
            data={"enabled": "0"},
        )
        assert r.status_code == 200
        assert "disabled" in r.text

    async def test_enable_missing_returns_404(self, client):
        r = await client.post(
            "/semantic-memory/missing/enable", data={"enabled": "1"},
        )
        assert r.status_code == 404

    async def test_search_query(self, client):
        await client.post(
            "/semantic-memory",
            data={"title": "alpha", "content": "about security"},
        )
        await client.post(
            "/semantic-memory",
            data={"title": "beta", "content": "about design"},
        )
        r = await client.get("/semantic-memory", params={"q": "design"})
        assert r.status_code == 200
        assert "beta" in r.text
        # alpha should not appear because its content does not match
        assert "<strong>alpha</strong>" not in r.text

    async def test_search_by_tag(self, client):
        await client.post(
            "/semantic-memory",
            data={"title": "tagged", "tags": "incident"},
        )
        await client.post(
            "/semantic-memory",
            data={"title": "untagged", "tags": "other"},
        )
        r = await client.get("/semantic-memory", params={"tag": "incident"})
        assert r.status_code == 200
        assert "tagged" in r.text
        assert "<strong>untagged</strong>" not in r.text
