"""TimingMiddleware: X-Response-Time-Ms header, INFO/WARN duration logs (#316)."""

from __future__ import annotations

import asyncio
import json
import logging

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from theswarm.presentation.web.timing import SLOW_REQUEST_THRESHOLD_MS, TimingMiddleware

LOGGER_NAME = "theswarm.timing"


def _make_app(*, delay_seconds: float = 0.0) -> Starlette:
    async def stub(request):
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/stub", stub)])
    app.add_middleware(TimingMiddleware)
    return app


async def _get(app: Starlette):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/stub")


async def test_fast_request_logs_info(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    response = await _get(_make_app())

    assert response.status_code == 200
    assert "x-response-time-ms" in response.headers
    assert float(response.headers["x-response-time-ms"]) < SLOW_REQUEST_THRESHOLD_MS

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    payload = json.loads(records[0].getMessage())
    assert payload["method"] == "GET"
    assert payload["path"] == "/stub"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] < SLOW_REQUEST_THRESHOLD_MS


async def test_slow_request_logs_warning_and_sets_header(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    delay = (SLOW_REQUEST_THRESHOLD_MS / 1000) + 0.1

    response = await _get(_make_app(delay_seconds=delay))

    assert response.status_code == 200
    header_ms = float(response.headers["x-response-time-ms"])
    assert header_ms > SLOW_REQUEST_THRESHOLD_MS

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    payload = json.loads(records[0].getMessage())
    assert payload["status_code"] == 200
    assert payload["duration_ms"] > SLOW_REQUEST_THRESHOLD_MS
