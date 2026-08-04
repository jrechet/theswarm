"""The liveness probe must answer quickly even when the DB is contended.

Prod repro (cycle 2f1b9a9515d3): every repo shares one aiosqlite connection
and aiosqlite serialises work per connection, so a running cycle queues
``/health``'s ``list_all()`` behind its checkpoint and event writes. Docker
allows 5s per healthcheck and kills the container after three failures —
which is exactly what happened mid-cycle ("task: non-zero exit (137):
unhealthy container"), taking the in-process cycle down with it.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from theswarm.presentation.web.routes import health as health_routes


class _SlowRepo:
    """Stands in for a connection saturated by a running cycle."""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    async def list_all(self):
        await asyncio.sleep(self._delay)
        return []


class _BrokenRepo:
    async def list_all(self):
        raise RuntimeError("database is gone")


def _app(project_repo) -> FastAPI:
    app = FastAPI()
    app.include_router(health_routes.router)
    app.state.project_repo = project_repo
    app.state.sse_hub = object()
    app.state.gateway_bridge = None
    return app


async def _get_health(project_repo):
    app = _app(project_repo)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


async def test_contended_db_still_reports_alive(monkeypatch):
    """A slow DB must not turn into a 503 that kills the container."""
    monkeypatch.setattr(health_routes, "_LIVENESS_DB_TIMEOUT_SECONDS", 0.05)

    started = time.monotonic()
    resp = await _get_health(_SlowRepo(delay=5.0))
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    assert resp.json()["checks"]["database"] == "busy"
    # Comfortably inside Docker's 5s healthcheck timeout
    assert elapsed < 1.0


async def test_healthy_db_reports_connected(monkeypatch):
    monkeypatch.setattr(health_routes, "_LIVENESS_DB_TIMEOUT_SECONDS", 1.0)

    resp = await _get_health(_SlowRepo(delay=0.0))

    assert resp.status_code == 200
    assert resp.json()["checks"]["database"] == "connected"
    assert resp.json()["status"] == "ok"


async def test_broken_db_is_still_an_error():
    """A genuinely broken DB must keep reporting 503 — only slowness is tolerated."""
    resp = await _get_health(_BrokenRepo())

    assert resp.status_code == 503
    assert resp.json()["checks"]["database"] == "error"


def test_busy_is_a_warning_not_an_error():
    assert health_routes._derive_status({"database": "busy"}) == "warn"
    assert health_routes._derive_status({"database": "error"}) == "error"
    assert health_routes._derive_status({"database": "connected"}) == "ok"


@pytest.mark.parametrize("value", ["busy", "missing"])
def test_warn_values_do_not_return_503(value):
    """503 fails `curl -f`, so only true errors may produce it."""
    assert health_routes._derive_status({"x": value}) != "error"
