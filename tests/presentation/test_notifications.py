"""Sprint D V5 — browser notifications opt-in UI and service worker."""

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


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "notif.db"))
    yield conn
    await conn.close()


async def _mk_app(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    return create_web_app(project_repo, cycle_repo, EventBus(), SSEHub())


async def test_dashboard_renders_notifications_button(db):
    app = await _mk_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert 'id="notifications-toggle"' in r.text
    assert 'data-state="idle"' in r.text
    # hidden until JS un-hides (only when Notification API is available)
    assert 'hidden' in r.text


async def test_service_worker_is_served(db):
    app = await _mk_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/static/js/sw.js")
    assert r.status_code == 200
    assert "notificationclick" in r.text
    assert "skipWaiting" in r.text


async def test_notifications_client_script_is_served(db):
    app = await _mk_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/static/js/notifications.js")
    assert r.status_code == 200
    assert "Notification" in r.text
    assert "__swarmShowDemoNotification" in r.text
    assert "requestPermission" in r.text


async def test_sse_client_dispatches_to_notification_handler(db):
    """The SSE client should hand off DemoReady events to the notification API."""
    app = await _mk_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/static/js/sse.js")
    assert r.status_code == 200
    assert "__swarmShowDemoNotification" in r.text
    assert "DemoReady" in r.text
