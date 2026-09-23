"""The repo page shows the reliability trend (V2 M6, dashboard #79)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm import evals
from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

REPO = "jrechet/concert-tour-app"


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


async def _page(client):
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=[])
        return await client.get(f"/r/{REPO}")


async def test_the_trend_is_drawn_from_the_harness_history(web, tmp_path, monkeypatch):
    history = tmp_path / "runs.jsonl"
    lines = [
        {"repo": REPO, "passed": True, "state": "completed", "prs": [1], "unfinished": [],
         "feature": "remaining-tickets", "cost_usd": 4.1, "duration_s": 1500, "backend": "sdk", "ci": "green"},
        {"repo": REPO, "passed": False, "state": "completed", "prs": [2], "unfinished": [3],
         "feature": "city-search", "cost_usd": 9.0, "duration_s": 4000, "backend": "sdk",
         "within_cost": False, "regression": True},
        {"repo": "other/repo", "passed": True},
    ]
    history.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    monkeypatch.setattr(evals, "HISTORY_PATH", history)

    response = await _page(web)

    assert response.status_code == 200
    html = response.text
    assert 'data-testid="evals"' in html
    assert "last 2 harness runs" in html
    assert "50% built" in html
    assert "regression on the last run" in html
    assert "sdk 1/2" in html
    assert html.count('<li class="w-3.5') == 2


async def test_no_history_means_no_panel(web, tmp_path, monkeypatch):
    monkeypatch.setattr(evals, "HISTORY_PATH", tmp_path / "missing.jsonl")
    response = await _page(web)
    assert response.status_code == 200
    assert 'data-testid="evals"' not in response.text
