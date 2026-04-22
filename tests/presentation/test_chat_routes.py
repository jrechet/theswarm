"""Presentation tests for Phase B chat + HITL routes."""

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
    conn = await init_db(str(tmp_path / "chatroutes.db"))
    yield conn
    await conn.close()


@pytest.fixture
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


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestChatRoutes:
    async def test_chat_index_is_empty_initially(self, client):
        r = await client.get("/chat")
        assert r.status_code == 200
        assert "No threads yet" in r.text

    async def test_project_chat_fragment_creates_team_thread(self, client):
        r = await client.get("/projects/demo/chat")
        assert r.status_code == 200
        assert "chat-composer" in r.text

    async def test_post_to_project_chat_returns_messages(self, client):
        r = await client.post(
            "/projects/demo/chat/messages", data={"body": "ping"},
        )
        assert r.status_code == 200
        assert "ping" in r.text
        assert "pong" in r.text

    async def test_thread_listed_after_posting(self, client):
        await client.post(
            "/projects/demo/chat/messages", data={"body": "ping"},
        )
        r = await client.get("/chat")
        assert r.status_code == 200
        # The thread row should be present
        assert "demo" in r.text


class TestHITLRoutes:
    async def test_nudge_creates_audit_entry(self, client):
        r = await client.post(
            "/cycles/cyc-1/nudge",
            data={"note": "push harder", "project_id": "demo"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["audit_id"].startswith("au_")

        # Audit entry visible on /hitl
        r2 = await client.get("/hitl")
        assert r2.status_code == 200
        assert "nudge" in r2.text
        assert "push harder" in r2.text

    async def test_pause_intervention(self, client):
        r = await client.post(
            "/cycles/cyc-1/pause",
            data={"project_id": "demo", "note": "blocked on prod"},
        )
        assert r.status_code == 200

    async def test_intervene_rejects_unknown_action(self, client):
        r = await client.post(
            "/cycles/cyc-1/intervene",
            data={"action": "bogus", "project_id": "demo"},
        )
        assert r.status_code == 400

    async def test_intervene_skip(self, client):
        r = await client.post(
            "/cycles/cyc-1/intervene",
            data={"action": "skip", "project_id": "demo", "target": "phase-dev"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_project_hitl_filters(self, client):
        await client.post(
            "/cycles/c1/nudge", data={"note": "A-note", "project_id": "A"},
        )
        await client.post(
            "/cycles/c2/nudge", data={"note": "B-note", "project_id": "B"},
        )
        r = await client.get("/projects/A/hitl")
        assert r.status_code == 200
        assert "A-note" in r.text
        assert "B-note" not in r.text
