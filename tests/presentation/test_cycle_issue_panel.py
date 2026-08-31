"""Cycle page shows what a targeted cycle is building (theswarm#25, P3).

The TechLead breakdown already creates sub-issues carrying ``Parent: #N``
and QA already stores per-story artifacts; none of it reached the UI. This
panel answers, while the cycle runs: which issue is being built, how it was
split, and where each sub-task stands.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from theswarm.api import CycleRequest, get_cycle_tracker
from theswarm.presentation.web.app import _TemplateEngine
from theswarm.presentation.web.routes import fragments as fragments_routes

TEMPLATES_DIR = "src/theswarm/presentation/web/templates"


@pytest.fixture(autouse=True)
def _isolate_tracker():
    tracker = get_cycle_tracker()
    known = set(tracker._cycles)
    yield
    for cycle_id in set(tracker._cycles) - known:
        tracker._cycles.pop(cycle_id, None)


class _FakeGitHub:
    """Repo with one parent story broken into three tasks."""

    CHILDREN = [
        {"number": 201, "title": "Model", "body": "…\n\nParent: #200",
         "labels": ["role:dev", "status:review"], "state": "closed"},
        {"number": 202, "title": "Endpoint", "body": "…\n\nParent: #200",
         "labels": ["role:dev", "status:in-progress"], "state": "open"},
        {"number": 203, "title": "Tests", "body": "…\n\nParent: #200",
         "labels": ["role:dev", "status:ready"], "state": "open"},
        {"number": 999, "title": "Unrelated", "body": "no parent here",
         "labels": ["status:ready"], "state": "open"},
    ]

    def __init__(self, repo: str) -> None:
        self.repo = repo

    async def get_issue(self, number: int):
        if number == 200:
            return {"number": 200, "title": "Tour dashboard",
                    "labels": ["status:in-progress"], "body": "", "state": "open"}
        return None

    async def get_issues(self, labels=None, state="open"):
        return list(self.CHILDREN)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(fragments_routes.router)
    app.state.templates = _TemplateEngine(TEMPLATES_DIR)
    app.state.base_path = ""
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _targeted_cycle(issue_number: int | None):
    return get_cycle_tracker().create(
        CycleRequest(repo="owner/repo", issue_number=issue_number),
    )


# ── The tracker has to remember the target ─────────────────────────────


def test_tracker_remembers_the_targeted_issue():
    assert _targeted_cycle(200).issue_number == 200
    assert _targeted_cycle(None).issue_number is None


# ── Panel ──────────────────────────────────────────────────────────────


async def test_panel_shows_the_issue_and_its_breakdown(monkeypatch):
    monkeypatch.setattr("theswarm.tools.github.GitHubClient", _FakeGitHub)
    record = _targeted_cycle(200)

    async with _client(_app()) as client:
        body = (await client.get(f"/fragments/cycle/{record.id}/issue")).text

    assert 'data-testid="cycle-issue"' in body
    assert "Tour dashboard" in body
    assert "https://github.com/owner/repo/issues/200" in body
    # Three children, the unrelated issue excluded
    assert "Split into 3 tasks" in body
    assert "1 in review" in body
    for number in (201, 202, 203):
        assert f'data-testid="child-{number}"' in body
    assert 'data-testid="child-999"' not in body


async def test_panel_renders_a_status_chip_per_child(monkeypatch):
    monkeypatch.setattr("theswarm.tools.github.GitHubClient", _FakeGitHub)
    record = _targeted_cycle(200)

    async with _client(_app()) as client:
        body = (await client.get(f"/fragments/cycle/{record.id}/issue")).text

    for chip in ("chip-review", "chip-in-progress", "chip-ready"):
        assert chip in body


async def test_panel_is_empty_for_an_untargeted_cycle():
    record = _targeted_cycle(None)

    async with _client(_app()) as client:
        resp = await client.get(f"/fragments/cycle/{record.id}/issue")

    assert resp.status_code == 200
    assert 'data-testid="cycle-issue"' not in resp.text


async def test_panel_is_empty_for_an_unknown_cycle():
    async with _client(_app()) as client:
        resp = await client.get("/fragments/cycle/deadbeef/issue")

    assert resp.status_code == 200
    assert 'data-testid="cycle-issue"' not in resp.text


async def test_panel_reports_a_task_implemented_directly(monkeypatch):
    class _NoChildren(_FakeGitHub):
        async def get_issues(self, labels=None, state="open"):
            return []

    monkeypatch.setattr("theswarm.tools.github.GitHubClient", _NoChildren)
    record = _targeted_cycle(200)

    async with _client(_app()) as client:
        body = (await client.get(f"/fragments/cycle/{record.id}/issue")).text

    assert "implemented directly" in body


async def test_panel_degrades_when_github_fails(monkeypatch):
    class _Broken:
        def __init__(self, repo): ...
        async def get_issue(self, number):
            raise RuntimeError("rate limited")

    monkeypatch.setattr("theswarm.tools.github.GitHubClient", _Broken)
    record = _targeted_cycle(200)

    async with _client(_app()) as client:
        resp = await client.get(f"/fragments/cycle/{record.id}/issue")

    assert resp.status_code == 200
    assert "rate limited" in resp.text
