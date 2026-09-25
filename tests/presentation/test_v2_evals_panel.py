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


def _write(tmp_path, monkeypatch, lines: list[dict]) -> None:
    history = tmp_path / "runs.jsonl"
    history.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    monkeypatch.setattr(evals, "HISTORY_PATH", history)


async def test_an_already_delivered_run_is_drawn_neutral_and_not_counted(web, tmp_path, monkeypatch):
    """Cycle 874f575645f2 found the city search already merged: not a
    failure, so not a rust square and not a point off the pass rate."""
    _write(tmp_path, monkeypatch, [
        {"repo": REPO, "passed": True, "outcome": "built", "feature": "city-search", "backend": "sdk"},
        {"repo": REPO, "passed": False, "outcome": "already_delivered", "feature": "city-search",
         "backend": "sdk", "already_satisfied": [286, 287, 288], "regression": False},
    ])

    html = (await _page(web)).text

    assert "100% built" in html
    assert "1 already delivered" in html
    assert "sdk 1/1" in html
    assert "regression on the last run" not in html
    assert html.count('<li class="w-3.5') == 2
    assert html.count("bg-faint") == 1
    assert "city-search — already delivered" in html


async def test_a_window_of_already_delivered_runs_says_nothing_was_measured(web, tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [
        {"repo": REPO, "passed": False, "outcome": "already_delivered", "feature": "city-search"},
    ])

    response = await _page(web)

    assert response.status_code == 200
    assert "nothing measured" in response.text
    assert "% built" not in response.text


async def test_a_built_run_with_a_pr_left_open_says_so(web, tmp_path, monkeypatch):
    """Cycle 9d3174f41829 scored "built" with three PRs; #325 never merged."""
    _write(tmp_path, monkeypatch, [
        {"repo": REPO, "passed": True, "outcome": "built", "feature": "", "backend": "sdk",
         "prs": [325, 326, 327], "merged": [326, 327], "unmerged": [325]},
        {"repo": REPO, "passed": True, "outcome": "built", "feature": "", "backend": "sdk",
         "prs": [336], "merged": [336], "unmerged": []},
    ])

    html = (await _page(web)).text

    assert "1 with PRs left open" in html
    assert "not merged: #325" in html
