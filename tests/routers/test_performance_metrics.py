"""#317: client-reported timing samples — POST /api/v1/metrics/performance."""

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


def _payload(**overrides) -> dict:
    payload = {
        "route": "/c/internal/p/concert-tour-app",
        "action": "click:play",
        "duration_ms": 123.4,
        "client_timestamp": "2026-10-08T12:00:00+00:00",
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await conn.close()


async def test_create_metric_returns_201(web):
    response = await web.post("/api/v1/metrics/performance", json=_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["id"] >= 1
    assert body["route"] == "/c/internal/p/concert-tour-app"
    assert body["action"] == "click:play"
    assert body["duration_ms"] == 123.4


async def test_create_metric_missing_field_returns_422(web):
    payload = _payload()
    del payload["duration_ms"]
    response = await web.post("/api/v1/metrics/performance", json=payload)
    assert response.status_code == 422


async def test_create_metric_negative_duration_returns_422(web):
    response = await web.post(
        "/api/v1/metrics/performance", json=_payload(duration_ms=-5)
    )
    assert response.status_code == 422
