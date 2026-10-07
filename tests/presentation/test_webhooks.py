"""Tests for webhook and report routes."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app


@pytest.fixture
async def app(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()
    web_app = create_web_app(project_repo, cycle_repo, bus)
    yield web_app
    await conn.close()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestWebhookRoute:
    async def test_webhook_no_handler_returns_501(self, client):
        resp = await client.post(
            "/webhooks/github",
            json={"action": "opened"},
            headers={"X-GitHub-Event": "push"},
        )
        assert resp.status_code == 501

    async def test_webhook_with_handler(self, app, client):
        from theswarm.infrastructure.scheduling.webhook_handler import WebhookHandler
        app.state.webhook_handler = WebhookHandler()
        app.state.allowed_repos = []

        resp = await client.post(
            "/webhooks/github",
            json={"repository": {"full_name": "o/r"}, "sender": {"login": "a"}},
            headers={"X-GitHub-Event": "push"},
        )
        assert resp.status_code == 200

    async def test_webhook_invalid_signature(self, app, client):
        from theswarm.infrastructure.scheduling.webhook_handler import WebhookHandler
        app.state.webhook_handler = WebhookHandler(webhook_secret="secret")
        app.state.allowed_repos = []

        resp = await client.post(
            "/webhooks/github",
            json={"test": True},
            headers={
                "X-GitHub-Event": "push",
                "X-Hub-Signature-256": "sha256=bad",
            },
        )
        assert resp.status_code == 401
