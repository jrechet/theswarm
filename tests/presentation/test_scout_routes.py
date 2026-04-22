"""Phase G presentation tests for Scout routes."""

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
    conn = await init_db(str(tmp_path / "scout_routes.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def app(db):
    bus = EventBus()
    hub = SSEHub()
    return create_web_app(
        SQLiteProjectRepository(db),
        SQLiteCycleRepository(db),
        bus,
        hub,
        db=db,
    )


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestIntelFeedRoutes:
    async def test_empty_portfolio_feed(self, client):
        r = await client.get("/intel/feed")
        assert r.status_code == 200
        assert "No intel items yet." in r.text
        # ingest form only shown at portfolio scope
        assert "Ingest" in r.text

    async def test_empty_project_feed(self, client):
        r = await client.get("/projects/demo/intel/feed")
        assert r.status_code == 200
        assert "No intel items yet." in r.text
        # no ingest form at project scope (portfolio-only)
        assert "Ingest" not in r.text

    async def test_ingest_then_feed_shows_item(self, client):
        r = await client.post(
            "/intel/feed",
            data={
                "title": "CVE in libfoo",
                "url": "https://example.com/cve-1",
                "category": "cve",
                "urgency": "high",
            },
        )
        assert r.status_code == 200
        assert "CVE in libfoo" in r.text
        assert "cve" in r.text

    async def test_ingest_dedup_still_renders(self, client):
        await client.post(
            "/intel/feed",
            data={"title": "x", "url": "https://a.test/x", "category": "fyi"},
        )
        r = await client.post(
            "/intel/feed",
            data={"title": "dup", "url": "https://a.test/x", "category": "fyi"},
        )
        # duplicate url_hash is silently dropped; page still renders
        assert r.status_code == 200
        assert "x" in r.text
        assert "dup" not in r.text

    async def test_classify_unknown_category_400(self, client):
        # ingest first
        await client.post(
            "/intel/feed",
            data={"title": "x", "url": "https://a/1", "category": "fyi"},
        )
        # grab portfolio feed so we can see the item id — but we didn't
        # expose ids in HTML. Use service side-effects via direct call
        # is out of scope; just confirm the 400 path for bogus input.
        r = await client.post(
            "/intel/items/missing/classify",
            data={"category": "not_a_real_category"},
        )
        assert r.status_code == 400


class TestIntelSourceRoutes:
    async def test_empty_sources(self, client):
        r = await client.get("/intel/sources")
        assert r.status_code == 200
        assert "No sources registered yet." in r.text
        assert "Register" in r.text

    async def test_register_and_list(self, client):
        r = await client.post(
            "/intel/sources",
            data={
                "name": "HackerNews",
                "kind": "hn",
                "url": "https://news.ycombinator.com",
            },
        )
        assert r.status_code == 200
        assert "HackerNews" in r.text
        assert "hn" in r.text

    async def test_project_scoped_sources_no_register_form(self, client):
        r = await client.get("/projects/demo/intel/sources")
        assert r.status_code == 200
        # portfolio-only form
        assert "Register" not in r.text


class TestIntelClusterRoutes:
    async def test_empty_clusters(self, client):
        r = await client.get("/intel/clusters")
        assert r.status_code == 200
        assert "No clusters yet." in r.text

    async def test_create_cluster(self, client):
        r = await client.post(
            "/intel/clusters",
            data={"topic": "Python 3.13", "summary": "big release"},
        )
        assert r.status_code == 200
        assert "Python 3.13" in r.text
