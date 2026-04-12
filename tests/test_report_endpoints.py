"""Tests for report API endpoints (migrated from legacy dashboard)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app


@pytest.fixture()
async def app(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()
    web_app = create_web_app(project_repo, cycle_repo, bus)
    yield web_app
    await conn.close()


@pytest.fixture()
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_dashboard_state():
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    state.reports = {}
    state.base_url = "https://bots.jrec.fr/swarm"
    state.github_repo = "owner/repo"
    yield
    state.reports = {}
    state.base_url = ""
    state.github_repo = ""


def _sample_result():
    return {
        "date": "2026-04-07",
        "cost_usd": 2.50,
        "tokens": 100000,
        "prs": [{"number": 1, "title": "Add login", "url": "#"}],
        "reviews": [{"pr_number": 1, "decision": "APPROVE", "summary": "ok"}],
        "demo_report": {"overall_status": "green", "quality_gates": {}, "metrics": {}},
        "daily_report": "All good.",
    }


# ── GET /api/reports/{date} ─────────────────────────────────────────


async def test_report_found(client):
    from theswarm.dashboard import get_dashboard_state
    get_dashboard_state().store_report("2026-04-07", _sample_result())

    resp = await client.get("/api/reports/2026-04-07")
    assert resp.status_code == 200
    data = resp.json()
    assert data["date"] == "2026-04-07"


async def test_report_not_found(client):
    resp = await client.get("/api/reports/1999-01-01")
    assert resp.status_code == 404


# ── GET /api/reports/weekly ─────────────────────────────────────────


async def test_weekly_report(client):
    entries = [{"date": "2026-04-07", "repo": "o/r", "cost_usd": 1.5}]

    with patch("theswarm.tools.github.GitHubClient"):
        with patch("theswarm.cycle_log.read_cycle_history", new_callable=AsyncMock, return_value=entries):
            resp = await client.get("/api/reports/weekly")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) == 1


async def test_weekly_report_no_repo(client):
    from theswarm.dashboard import get_dashboard_state
    get_dashboard_state().github_repo = ""

    resp = await client.get("/api/reports/weekly")
    assert resp.status_code == 404


# ── POST /api/reports/{date}/approve/{pr_number} ────────────────────


async def test_approve_pr(client):
    mock_github = AsyncMock()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        resp = await client.post("/api/reports/2026-04-07/approve/42")

    assert resp.status_code == 200
    assert resp.json()["merged"] is True
    mock_github.merge_pr.assert_awaited_once_with(42)


async def test_approve_pr_failure(client):
    mock_github = AsyncMock()
    mock_github.merge_pr.side_effect = Exception("Conflict")
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        resp = await client.post("/api/reports/2026-04-07/approve/42")

    assert resp.status_code == 500


# ── POST /api/reports/{date}/comment/{pr_number} ────────────────────


async def test_comment_on_pr(client):
    mock_github = AsyncMock()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        resp = await client.post(
            "/api/reports/2026-04-07/comment/42",
            json={"comment": "Header color too dark"},
        )

    assert resp.status_code == 200
    assert resp.json()["posted"] is True
    mock_github.create_pr_comment.assert_awaited_once_with(42, "Header color too dark")


async def test_comment_on_pr_empty(client):
    resp = await client.post(
        "/api/reports/2026-04-07/comment/42",
        json={"comment": ""},
    )
    assert resp.status_code == 400


async def test_comment_on_pr_failure(client):
    mock_github = AsyncMock()
    mock_github.create_pr_comment.side_effect = Exception("API error")
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        resp = await client.post(
            "/api/reports/2026-04-07/comment/42",
            json={"comment": "Fix this"},
        )

    assert resp.status_code == 500


# ── DashboardState.store_report ─────────────────────────────────────


def test_store_report_basic():
    from theswarm.dashboard import DashboardState
    state = DashboardState()
    state.store_report("2026-04-07", {"date": "2026-04-07"})
    assert "2026-04-07" in state.reports


def test_store_report_cap():
    from theswarm.dashboard import DashboardState
    state = DashboardState()
    for i in range(35):
        state.store_report(f"2026-01-{i+1:02d}", {"date": f"2026-01-{i+1:02d}"})
    assert len(state.reports) == 30
