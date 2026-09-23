"""V2 M6: scored harness runs live in the swarm's database, not only in a
jsonl the branch protection refuses to receive."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm import evals
from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteEvalRunRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

REPO = "jrechet/concert-tour-app"


def _record(**overrides) -> dict:
    record = {
        "repo": REPO, "passed": True, "state": "completed", "prs": [263], "unfinished": [],
        "feature": "remaining-tickets", "cost_usd": 1.47, "duration_s": 690, "backend": "sdk",
        "ci": "none", "cycle_id": "e4978adebe03", "timestamp": "2026-09-23T14:37:00+00:00",
    }
    record.update(overrides)
    return record


async def test_the_repository_keeps_records_oldest_first(tmp_path):
    db = await init_db(str(tmp_path / "t.db"))
    try:
        store = SQLiteEvalRunRepository(db)
        await store.save(_record(feature="a"))
        await store.save(_record(feature="b", passed=False))
        await store.save({"repo": "other/repo", "passed": True})
        runs = await store.list_for_repo(REPO)
        assert [r["feature"] for r in runs] == ["a", "b"]
        assert (await store.list_for_repo(REPO, limit=1))[0]["feature"] == "b"
        assert await store.list_for_repo("nobody/nothing") == []
    finally:
        await db.close()


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


async def test_the_harness_posts_and_the_api_lists(web):
    response = await web.post("/api/evals/runs", json=_record())
    assert response.status_code == 201 and response.json()["id"] >= 1
    listed = await web.get("/api/evals/runs", params={"repo": REPO})
    assert [r["cycle_id"] for r in listed.json()["runs"]] == ["e4978adebe03"]


async def test_a_record_without_a_repo_is_refused(web):
    assert (await web.post("/api/evals/runs", json={"passed": True})).status_code == 422
    assert (await web.post("/api/evals/runs", content=b"not json",
                           headers={"Content-Type": "application/json"})).status_code == 400


async def test_the_repo_page_reads_the_posted_runs_before_the_shipped_file(web, tmp_path, monkeypatch):
    stale = tmp_path / "runs.jsonl"
    stale.write_text(json.dumps({"repo": REPO, "passed": False, "feature": "stale"}) + "\n")
    monkeypatch.setattr(evals, "HISTORY_PATH", stale)
    await web.post("/api/evals/runs", json=_record())
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=[])
        page = await web.get(f"/r/{REPO}")
    assert page.status_code == 200
    assert "100% built" in page.text
    assert "stale" not in page.text


async def test_without_posted_runs_the_shipped_file_still_draws_the_trend(web, tmp_path, monkeypatch):
    history = tmp_path / "runs.jsonl"
    history.write_text(json.dumps({"repo": REPO, "passed": True, "feature": "old"}) + "\n")
    monkeypatch.setattr(evals, "HISTORY_PATH", history)
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=[])
        page = await web.get(f"/r/{REPO}")
    assert 'data-testid="evals"' in page.text and "100% built" in page.text
