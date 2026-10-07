"""A skipped review is counted, not only logged (#79, #147).

Since #150 a review call that fails leaves its PR for the next pass, and a
review phase that times out leaves every PR for the next cycle: nothing
kills the cycle any more. But nothing counted it either — "3 timeouts in 7
cycles" was read off logs by hand, and on the SDK nobody knew the number.
The cycle keeps each skip (`review_skips`), its result carries them, the
eval scores `reviews_skipped`, and the repo page says so.
"""

from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from theswarm import cycle_graph, evals
from theswarm.cycle_budgets import PhaseTimeout

_SPEC = importlib.util.spec_from_file_location(
    "cycle_e2e", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cycle_e2e.py"
)
cycle_e2e = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cycle_e2e)



async def _v3(client, path, **kw):
    """A V2 address registers the project under Internal and redirects (303,
    under the base path); the page itself is read at its V3 address."""
    await client.get(path.split("?")[0], **kw)
    name = path.split("?")[0][len("/r/"):].split("/", 1)[1]
    return await client.get(f"/c/internal/p/{name}", **kw)

def _runtime():
    rt = SimpleNamespace(
        announce=AsyncMock(), progress=AsyncMock(), base_state={},
        config=SimpleNamespace(github_repo="o/r"),
    )
    return SimpleNamespace(context=rt), rt


@pytest.fixture()
def review_node(monkeypatch):
    """The review node with its phase answered by the test."""
    answer: dict = {}

    async def run_phase(rt, key, role, coro):
        if answer.get("raise"):
            raise answer["raise"]
        return answer["state"]

    monkeypatch.setattr(cycle_graph, "_run_phase", run_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", lambda graph, state: None)
    monkeypatch.setattr(cycle_graph, "_accounted", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph, "_within_budget", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph._cycle(), "build_techlead_graph", lambda: object())
    return answer


async def test_a_review_call_that_failed_is_kept_as_a_skip(review_node):
    review_node["state"] = {"skipped_prs": [146], "reviews": [], "reviewed_prs": []}
    runtime, rt = _runtime()
    earlier = [{"pr": 140, "iteration": 1, "why": "review call failed"}]

    updates = await cycle_graph.techlead_review(
        {"iteration": 2, "review_skips": earlier}, runtime,
    )

    assert updates["review_skips"] == [
        *earlier, {"pr": 146, "iteration": 2, "why": "review call failed"},
    ]


async def test_a_review_phase_that_timed_out_is_kept_as_a_skip(review_node):
    review_node["raise"] = PhaseTimeout("techlead_review", 1800)
    runtime, rt = _runtime()

    updates = await cycle_graph.techlead_review(
        {"iteration": 3, "reviewed_prs": ["392@abc"]}, runtime,
    )

    assert updates["reviewed_prs"] == ["392@abc"]
    assert updates["review_skips"] == [{"pr": None, "iteration": 3, "why": "review phase timed out"}]


async def test_a_clean_review_pass_adds_no_skip(review_node):
    review_node["state"] = {"reviews": [{"pr_number": 392, "decision": "APPROVE"}],
                            "reviewed_prs": ["392@abc"]}
    runtime, _ = _runtime()

    updates = await cycle_graph.techlead_review({"iteration": 1}, runtime)

    assert updates.get("review_skips", []) == []


def test_the_cycle_state_declares_the_skips():
    """A key the graph state does not declare is dropped at the checkpoint."""
    assert "review_skips" in cycle_graph.CycleState.__annotations__


async def test_the_cycle_result_carries_the_skips(monkeypatch):
    runtime, rt = _runtime()
    rt.config = SimpleNamespace(github_repo="", is_real_mode=False)
    skips = [{"pr": 146, "iteration": 2, "why": "review call failed"}]
    monkeypatch.setattr("theswarm.tools.claude._resolve_backend_mode", lambda: "sdk")

    updates = await cycle_graph.finish({"review_skips": skips}, runtime)

    assert updates["result"]["review_skips"] == skips


# ── The score and the page ───────────────────────────────────────────


def test_the_score_counts_the_skipped_reviews():
    record = evals.score(None, evals.Observed(state="completed", prs=(392,), reviews_skipped=2))

    assert record["reviews_skipped"] == 2


def test_the_trend_sums_the_skipped_reviews_of_the_window():
    summary = evals.trend([
        {"passed": True, "outcome": "built", "reviews_skipped": 2},
        {"passed": True, "outcome": "built"},  # a record from before the field
        {"passed": True, "outcome": "built", "reviews_skipped": 1},
    ])

    assert summary["reviews_skipped"] == 3


def test_the_harness_reads_the_skips_off_the_cycle_result():
    assert cycle_e2e.reviews_skipped({"review_skips": [{"pr": 1}, {"pr": None}]}) == 2
    assert cycle_e2e.reviews_skipped({}) == 0
    assert cycle_e2e.reviews_skipped(None) == 0


async def test_the_repo_page_says_how_many_reviews_were_skipped(tmp_path, monkeypatch):
    import json
    from unittest.mock import patch

    from httpx import ASGITransport, AsyncClient

    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository, SQLiteProjectRepository, init_db,
    )
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    history = tmp_path / "runs.jsonl"
    history.write_text(json.dumps({"repo": "o/r", "passed": True, "outcome": "built",
                                   "reviews_skipped": 2}) + "\n")
    monkeypatch.setattr(evals, "HISTORY_PATH", history)
    conn = await init_db(str(tmp_path / "t.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
                         EventBus(), SSEHub(), base_path="", db=conn)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            with patch("theswarm.tools.github.GitHubClient") as klass:
                klass.return_value.get_issues = AsyncMock(return_value=[])
                html = (await _v3(client, "/r/o/r")).text
    finally:
        await conn.close()

    assert 'data-testid="evals-reviews-skipped"' in html and "2 reviews skipped" in html
