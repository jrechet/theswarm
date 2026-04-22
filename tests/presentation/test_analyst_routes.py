"""Phase J presentation tests for Analyst routes."""

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
    conn = await init_db(str(tmp_path / "analyst_routes.db"))
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


class TestMetricRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/analyst/metrics")
        assert r.status_code == 200
        assert "No metrics defined yet." in r.text

    async def test_upsert(self, client):
        r = await client.post(
            "/projects/demo/analyst/metrics",
            data={
                "name": "signup_conversion",
                "kind": "ratio",
                "unit": "%",
                "definition": "signups / visitors",
                "target": ">20%",
            },
        )
        assert r.status_code == 200
        assert "signup_conversion" in r.text
        assert ">20%" in r.text
        assert "ratio" in r.text

    async def test_unknown_kind_falls_back(self, client):
        r = await client.post(
            "/projects/demo/analyst/metrics",
            data={"name": "foo", "kind": "bogus"},
        )
        assert r.status_code == 200
        assert "counter" in r.text


class TestInstrumentationRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/analyst/instrumentation")
        assert r.status_code == 200
        assert "No instrumentation plans yet." in r.text

    async def test_propose_then_verify(self, client):
        r = await client.post(
            "/projects/demo/analyst/instrumentation",
            data={
                "story_id": "S42",
                "metric_name": "signup_conversion",
                "hypothesis": "expect +5pp",
                "method": "posthog funnel",
            },
        )
        assert r.status_code == 200
        assert "S42" in r.text
        assert "proposed" in r.text
        assert "posthog funnel" in r.text

        r = await client.post(
            "/projects/demo/analyst/instrumentation/S42/signup_conversion/status",
            data={"status": "verified", "note": "landed in #123"},
        )
        assert r.status_code == 200
        assert "verified" in r.text
        assert "landed in #123" in r.text

    async def test_missing_flags_blocking(self, client):
        await client.post(
            "/projects/demo/analyst/instrumentation",
            data={
                "story_id": "S1", "metric_name": "conv",
                "status": "missing",
            },
        )
        r = await client.get("/projects/demo/analyst/instrumentation")
        assert r.status_code == 200
        assert "missing" in r.text
        assert "blocks outcome" in r.text

    async def test_unknown_status_400(self, client):
        r = await client.post(
            "/projects/demo/analyst/instrumentation/S1/conv/status",
            data={"status": "bogus"},
        )
        assert r.status_code == 400


class TestOutcomeRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/analyst/outcomes")
        assert r.status_code == 200
        assert "No outcome observations yet." in r.text

    async def test_record_improved(self, client):
        r = await client.post(
            "/projects/demo/analyst/outcomes",
            data={
                "story_id": "S42",
                "metric_name": "signup_conversion",
                "baseline": "18.2%",
                "observed": "22.4%",
                "direction": "improved",
                "window": "7d",
            },
        )
        assert r.status_code == 200
        assert "S42" in r.text
        assert "improved" in r.text
        assert "18.2%" in r.text
        assert "22.4%" in r.text

    async def test_unknown_direction_falls_back(self, client):
        r = await client.post(
            "/projects/demo/analyst/outcomes",
            data={
                "story_id": "S1", "metric_name": "x",
                "direction": "bogus",
            },
        )
        assert r.status_code == 200
        assert "inconclusive" in r.text
