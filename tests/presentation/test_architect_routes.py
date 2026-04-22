"""Phase K presentation tests for Architect routes."""

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
    conn = await init_db(str(tmp_path / "architect_routes.db"))
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


class TestPavedRoadRoutes:
    async def test_empty(self, client):
        r = await client.get("/architect/paved-road")
        assert r.status_code == 200
        assert "No paved-road rules yet." in r.text

    async def test_upsert_creates_rule(self, client):
        r = await client.post(
            "/architect/paved-road",
            data={
                "name": "python-uv",
                "rule": "All Python projects use uv",
                "rationale": "consistency",
                "severity": "required",
                "tags": "python, deps",
            },
        )
        assert r.status_code == 200
        assert "python-uv" in r.text
        assert "required" in r.text
        assert "blocks merge" in r.text

    async def test_unknown_severity_falls_back(self, client):
        r = await client.post(
            "/architect/paved-road",
            data={"name": "x", "rule": "r", "severity": "bogus"},
        )
        assert r.status_code == 200
        assert "advisory" in r.text


class TestPortfolioADRRoutes:
    async def test_portfolio_empty(self, client):
        r = await client.get("/architect/adrs")
        assert r.status_code == 200
        assert "No ADRs recorded yet." in r.text

    async def test_propose_accept_reject_portfolio(self, client):
        r = await client.post(
            "/architect/adrs",
            data={
                "title": "Use LangGraph",
                "context": "ctx",
                "decision": "dec",
                "consequences": "csq",
            },
        )
        assert r.status_code == 200
        assert "Use LangGraph" in r.text
        assert "proposed" in r.text

    async def test_project_scoped_create(self, client):
        r = await client.post(
            "/projects/p1/architect/adrs",
            data={"title": "proj-scoped", "decision": "d"},
        )
        assert r.status_code == 200
        assert "proj-scoped" in r.text

    async def test_accept_missing_404(self, client):
        r = await client.post("/architect/adrs/missing/accept")
        assert r.status_code == 404

    async def test_reject_missing_404(self, client):
        r = await client.post("/architect/adrs/missing/reject")
        assert r.status_code == 404


class TestDirectionBriefRoutes:
    async def test_portfolio_empty(self, client):
        r = await client.get("/architect/briefs")
        assert r.status_code == 200
        assert "No direction briefs yet." in r.text

    async def test_record_portfolio_brief(self, client):
        r = await client.post(
            "/architect/briefs",
            data={
                "title": "2026-Q2",
                "period": "2026-Q2",
                "author": "@jre",
                "focus_areas": "Resilience\nObservability",
                "risks": "Rate limits",
                "narrative": "The story.",
            },
        )
        assert r.status_code == 200
        assert "2026-Q2" in r.text
        assert "Resilience" in r.text
        assert "Observability" in r.text
        assert "Rate limits" in r.text

    async def test_record_project_brief(self, client):
        r = await client.post(
            "/projects/p1/architect/briefs",
            data={"title": "proj Q2"},
        )
        assert r.status_code == 200
        assert "proj Q2" in r.text

    async def test_project_list_empty(self, client):
        r = await client.get("/projects/p1/architect/briefs")
        assert r.status_code == 200
        assert "No direction briefs yet." in r.text
