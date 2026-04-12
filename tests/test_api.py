"""Tests for theswarm.api — CycleTracker and headless cycle management."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.api import (
    CycleRecord,
    CycleRequest,
    CycleStatus,
    CycleTracker,
    get_cycle_tracker,
)
from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app


# ── CycleTracker ────────────────────────────────────────────────────


def test_tracker_create():
    tracker = CycleTracker()
    req = CycleRequest(repo="owner/repo", description="Add login")
    record = tracker.create(req)
    assert record.repo == "owner/repo"
    assert record.description == "Add login"
    assert record.status == CycleStatus.QUEUED
    assert len(record.id) == 12


def test_tracker_get():
    tracker = CycleTracker()
    req = CycleRequest(repo="owner/repo")
    record = tracker.create(req)
    assert tracker.get(record.id) is not None
    assert tracker.get("nonexistent") is None


def test_tracker_list_recent():
    tracker = CycleTracker()
    for i in range(5):
        tracker.create(CycleRequest(repo=f"owner/repo{i}"))
    records = tracker.list_recent(limit=3)
    assert len(records) == 3


def test_tracker_update_status():
    tracker = CycleTracker()
    record = tracker.create(CycleRequest(repo="owner/repo"))
    tracker.update_status(record.id, CycleStatus.RUNNING, started_at="2026-04-07T10:00:00")
    updated = tracker.get(record.id)
    assert updated.status == CycleStatus.RUNNING
    assert updated.started_at == "2026-04-07T10:00:00"


def test_tracker_cap_at_100():
    tracker = CycleTracker()
    for i in range(110):
        tracker.create(CycleRequest(repo=f"owner/repo{i}"))
    assert len(tracker._cycles) <= 100


def test_tracker_cancel():
    tracker = CycleTracker()
    record = tracker.create(CycleRequest(repo="owner/repo"))

    loop = asyncio.new_event_loop()
    async def dummy(): await asyncio.sleep(100)
    task = loop.create_task(dummy())
    tracker.set_task(record.id, task)

    cancelled = tracker.cancel(record.id)
    assert cancelled is True
    assert tracker.get(record.id).status == CycleStatus.CANCELLED
    loop.close()


def test_tracker_cancel_nonexistent():
    tracker = CycleTracker()
    assert tracker.cancel("nonexistent") is False


# ── API endpoint tests ──────────────────────────────────────────────


@pytest.fixture()
async def api_app(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()
    app = create_web_app(project_repo, cycle_repo, bus)
    app.state.allowed_repos = ["owner/repo", "owner/other"]
    yield app
    await conn.close()


@pytest.fixture()
async def client(api_app):
    async with AsyncClient(transport=ASGITransport(app=api_app), base_url="http://test") as c:
        yield c


async def test_start_cycle(client):
    with patch("theswarm.api.run_api_cycle", new_callable=AsyncMock):
        resp = await client.post("/api/cycle", json={
            "repo": "owner/repo",
            "description": "Add login feature",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert "cycle_id" in data
    assert data["status"] == "queued"
    assert data["repo"] == "owner/repo"


async def test_get_cycle(client):
    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/repo"))
    tracker.update_status(record.id, CycleStatus.COMPLETED, result={"cost_usd": 1.5})

    resp = await client.get(f"/api/cycles/{record.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == record.id
    assert data["status"] == "completed"


async def test_get_cycle_not_found(client):
    resp = await client.get("/api/cycles/nonexistent")
    assert resp.status_code == 404


async def test_list_cycles(client):
    tracker = get_cycle_tracker()
    for i in range(3):
        tracker.create(CycleRequest(repo=f"owner/repo{i}"))

    resp = await client.get("/api/cycles?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["cycles"]) >= 2


async def test_cancel_cycle(client):
    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/repo"))

    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_task.cancel.return_value = True
    tracker.set_task(record.id, mock_task)

    resp = await client.post(f"/api/cycle/{record.id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True


async def test_cancel_completed_cycle(client):
    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/repo"))
    tracker.update_status(record.id, CycleStatus.COMPLETED)

    resp = await client.post(f"/api/cycle/{record.id}/cancel")
    assert resp.status_code == 409
