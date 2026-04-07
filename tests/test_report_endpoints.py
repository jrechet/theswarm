"""Tests for report-serving endpoints in dashboard.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI


@pytest.fixture()
def report_app():
    """Fresh FastAPI app with dashboard+report routes."""
    app = FastAPI()
    from theswarm.dashboard import register_dashboard_routes, get_dashboard_state
    register_dashboard_routes(app)
    state = get_dashboard_state()
    # Reset for test isolation
    state.reports = {}
    state.base_url = "https://bots.jrec.fr/swarm"
    state.github_repo = "owner/repo"
    yield app
    # Cleanup
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


# ── GET /swarm/reports/{date} ────────────────────────────────────────


async def test_report_page_found(report_app):
    from theswarm.dashboard import get_dashboard_state
    get_dashboard_state().store_report("2026-04-07", _sample_result())

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
        resp = await client.get("/swarm/reports/2026-04-07")

    assert resp.status_code == 200
    assert "TheSwarm Report" in resp.text
    assert "2026-04-07" in resp.text


async def test_report_page_not_found(report_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
        resp = await client.get("/swarm/reports/1999-01-01")

    assert resp.status_code == 404
    assert "No report" in resp.text


# ── GET /swarm/reports/weekly ────────────────────────────────────────


async def test_weekly_report(report_app):
    entries = [{"date": "2026-04-07", "repo": "o/r", "cost_usd": 1.5, "tokens": 50000,
                "prs_opened": 2, "prs_merged": 1, "demo_status": "green"}]

    with patch("theswarm.tools.github.GitHubClient"):
        with patch("theswarm.cycle_log.read_cycle_history", new_callable=AsyncMock, return_value=entries):
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
                resp = await client.get("/swarm/reports/weekly")

    assert resp.status_code == 200
    assert "Weekly" in resp.text


async def test_weekly_report_no_repo(report_app):
    from theswarm.dashboard import get_dashboard_state
    get_dashboard_state().github_repo = ""

    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
        resp = await client.get("/swarm/reports/weekly")

    assert resp.status_code == 404


# ── POST /swarm/reports/{date}/approve/{pr_number} ───────────────────


async def test_approve_pr(report_app):
    mock_github = AsyncMock()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
            resp = await client.post("/swarm/reports/2026-04-07/approve/42")

    assert resp.status_code == 200
    assert "merged" in resp.text.lower()
    mock_github.merge_pr.assert_awaited_once_with(42)


async def test_approve_pr_failure(report_app):
    mock_github = AsyncMock()
    mock_github.merge_pr.side_effect = Exception("Conflict")
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
            resp = await client.post("/swarm/reports/2026-04-07/approve/42")

    assert resp.status_code == 500
    assert "Failed" in resp.text


# ── POST /swarm/reports/{date}/comment/{pr_number} ───────────────────


async def test_comment_on_pr(report_app):
    mock_github = AsyncMock()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
            resp = await client.post(
                "/swarm/reports/2026-04-07/comment/42",
                data={"comment": "Header color too dark"},
            )

    assert resp.status_code == 200
    assert "Comment posted" in resp.text
    mock_github.create_pr_comment.assert_awaited_once_with(42, "Header color too dark")


async def test_comment_on_pr_empty(report_app):
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
        resp = await client.post(
            "/swarm/reports/2026-04-07/comment/42",
            data={"comment": ""},
        )

    assert resp.status_code == 400
    assert "No comment" in resp.text


async def test_comment_on_pr_failure(report_app):
    mock_github = AsyncMock()
    mock_github.create_pr_comment.side_effect = Exception("API error")
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=report_app), base_url="http://test") as client:
            resp = await client.post(
                "/swarm/reports/2026-04-07/comment/42",
                data={"comment": "Fix this"},
            )

    assert resp.status_code == 500


# ── DashboardState.store_report ──────────────────────────────────────


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
