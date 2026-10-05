"""`/health/ready` knows the subscription answers Claude calls.

Its `anthropic_key` check was an "error" without an API key — on every boot
of a deployment that runs, by design, on the Agent SDK and the subscription
(V2 invariant I1), and on the Quickstart's first `validate` (2026-10-05).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _app() -> FastAPI:
    from theswarm.presentation.web.routes import health as health_routes

    app = FastAPI()
    app.include_router(health_routes.router)
    app.state.project_repo = None
    app.state.sse_hub = object()
    app.state.gateway_bridge = None
    app.state.secret_vault = None
    return app


async def _anthropic_check(monkeypatch, backend: str, key: str | None) -> dict:
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", backend)
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/health/ready")
    return response.json()["checks"]["anthropic_key"]


@pytest.mark.parametrize("backend", ["sdk", "auto"])
async def test_no_api_key_is_ok_on_the_subscription(monkeypatch, backend):
    check = await _anthropic_check(monkeypatch, backend, None)

    assert check["status"] == "ok" and "subscription" in check["detail"] and "fallback off" in check["detail"]


async def test_the_api_backend_without_a_key_is_an_error(monkeypatch):
    check = await _anthropic_check(monkeypatch, "api", None)

    assert check["status"] == "error" and "SWARM_CLAUDE_BACKEND=api" in check["detail"]


async def test_a_key_on_the_subscription_is_the_fallback(monkeypatch):
    check = await _anthropic_check(monkeypatch, "sdk", "sk-ant-api03-test")

    assert check["status"] == "ok" and "fallback on" in check["detail"]
