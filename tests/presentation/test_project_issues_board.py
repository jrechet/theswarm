"""Issue board with a Play button (theswarm#24, issue-driven flow P2).

The project page lists the target repo's GitHub issues grouped by
``status:*`` label; pressing ▶ starts a cycle pinned to that issue and sends
the user to it. Backend targeting landed in #23 — this is the surface that
makes it usable without curl.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from theswarm.presentation.web.app import _TemplateEngine

from theswarm.presentation.web.routes import projects as projects_routes

TEMPLATES_DIR = "src/theswarm/presentation/web/templates"


@pytest.fixture(autouse=True)
def _isolate_cycle_tracker():
    """Play registers a cycle in the process-wide tracker; the dashboard
    reads that same singleton, so anything left behind leaks into other
    test modules."""
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    known = set(tracker._cycles)
    yield
    for cycle_id in set(tracker._cycles) - known:
        task = tracker._tasks.pop(cycle_id, None)
        if task is not None and not task.done():
            task.cancel()
        tracker._cycles.pop(cycle_id, None)


@pytest.fixture(autouse=True)
def _github_token_by_default(monkeypatch):
    """The board now runs a credential precheck (theswarm#63) before it asks
    GitHub for issues. Give every test in this module a token so tests about
    the issue listing itself aren't accidentally short-circuited by that
    precheck; the tests that exercise the precheck clear it themselves."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token_for_suite")
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)


class _FakeGitHub:
    def __init__(self, repo: str) -> None:
        self.repo = repo

    async def get_issues(self, labels=None, state="open"):
        return [
            {"number": 186, "title": "Add GET /dashboard route",
             "labels": ["status:ready", "role:dev"], "body": ""},
            {"number": 187, "title": "HTMX partials",
             "labels": ["status:in-progress", "role:dev"], "body": ""},
            {"number": 188, "title": "Shipped work",
             "labels": ["status:review", "role:dev"], "body": ""},
            {"number": 189, "title": "Someday", "labels": [], "body": ""},
        ]


def _app(project=SimpleNamespace(id="p1", repo="owner/repo")) -> FastAPI:
    app = FastAPI()
    app.include_router(projects_routes.router)
    app.state.templates = _TemplateEngine(TEMPLATES_DIR)
    app.state.base_path = ""
    app.state.get_project_query = SimpleNamespace(
        execute=lambda _pid: _resolved(project),
    )
    for attr in ("allowed_repos", "event_bus", "report_repo", "project_repo",
                 "cycle_repo", "role_assignment_service"):
        setattr(app.state, attr, None)
    app.state.allowed_repos = []
    return app


async def _resolved(value):
    return value


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── Status grouping ────────────────────────────────────────────────────


def test_issue_status_reads_the_status_label():
    assert projects_routes._issue_status({"labels": ["status:ready"]}) == "ready"
    assert projects_routes._issue_status({"labels": ["status:review"]}) == "review"
    # dict-shaped labels (PyGithub) and unknown/absent statuses
    assert projects_routes._issue_status({"labels": [{"name": "status:in-progress"}]}) == "in-progress"
    assert projects_routes._issue_status({"labels": ["role:dev"]}) == "backlog"
    assert projects_routes._issue_status({}) == "backlog"


# ── Board rendering ────────────────────────────────────────────────────


async def test_board_groups_issues_by_status():
    with patch("theswarm.tools.github.GitHubClient", _FakeGitHub):
        async with _client(_app()) as client:
            resp = await client.get("/projects/p1/issues")

    assert resp.status_code == 200
    body = resp.text
    for name in ("ready", "in-progress", "review", "backlog"):
        assert f'data-testid="issues-column-{name}"' in body
    assert 'data-testid="issue-186"' in body
    assert "Add GET /dashboard route" in body
    # Links back to the real issue
    assert "https://github.com/owner/repo/issues/186" in body


async def test_play_button_targets_the_issue_and_skips_review():
    with patch("theswarm.tools.github.GitHubClient", _FakeGitHub):
        async with _client(_app()) as client:
            body = (await client.get("/projects/p1/issues")).text

    assert 'hx-post="/projects/p1/issues/186/play"' in body
    assert 'data-testid="play-186"' in body
    # An issue already in review has nothing left to implement
    assert 'data-testid="play-188"' not in body


async def test_board_surfaces_github_errors_without_failing():
    class _Broken:
        def __init__(self, repo): ...
        async def get_issues(self, **kw):
            raise RuntimeError("bad credentials")

    with patch("theswarm.tools.github.GitHubClient", _Broken):
        async with _client(_app()) as client:
            resp = await client.get("/projects/p1/issues")

    assert resp.status_code == 200  # panel degrades, page still renders
    assert "bad credentials" in resp.text
    assert 'data-testid="issues-error"' in resp.text
    assert 'data-testid="issues-credential-error"' not in resp.text


async def test_board_404s_for_an_unknown_project():
    app = _app(project=None)
    async with _client(app) as client:
        assert (await client.get("/projects/nope/issues")).status_code == 404


# ── GitHub credential precheck (theswarm#63) ────────────────────────────


async def test_board_reports_missing_github_token(monkeypatch):
    """No GITHUB_TOKEN (and no App creds): name the repo and say so, instead
    of a cryptic PyGitHub error or a silent empty board."""
    from theswarm.tools import github_app

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    github_app.reset_state()

    async with _client(_app()) as client:
        resp = await client.get("/projects/p1/issues")

    assert resp.status_code == 200
    body = resp.text
    assert "owner/repo" in body
    assert "token" in body.lower()
    assert (
        'data-testid="issues-error"' in body
        or 'data-testid="issues-credential-error"' in body
    )


async def test_board_distinguishes_no_access_from_missing_token():
    """A rejected-but-present credential (reason='no_access') must read
    differently from a missing token, not repeat the same wording."""
    from theswarm.tools.github import GitHubAccessError

    async def _no_access(repo_name):
        raise GitHubAccessError(repo_name, "no_access")

    with patch("theswarm.tools.github.verify_access", _no_access):
        async with _client(_app()) as client:
            resp = await client.get("/projects/p1/issues")

    assert resp.status_code == 200
    assert "access" in resp.text
    assert "no GitHub token configured" not in resp.text
    assert 'data-testid="issues-credential-error"' in resp.text


# ── Play action ────────────────────────────────────────────────────────


async def test_play_starts_a_cycle_pinned_to_the_issue():
    captured: dict = {}

    async def fake_run(cycle_id, repo, description, callback_url, allowed, **kwargs):
        captured["repo"] = repo
        captured["issue_number"] = kwargs.get("issue_number")
        captured["cycle_id"] = cycle_id

    with patch("theswarm.api.run_api_cycle", side_effect=fake_run):
        async with _client(_app()) as client:
            resp = await client.post("/projects/p1/issues/186/play")

    assert resp.status_code == 200
    redirect = resp.headers["HX-Redirect"]
    assert redirect.startswith("/cycles/")

    # The cycle was registered against the right repo and issue
    from theswarm.api import get_cycle_tracker

    record = get_cycle_tracker().get(redirect.rsplit("/", 1)[1])
    assert record is not None
    assert record.repo == "owner/repo"


async def test_play_404s_for_an_unknown_project():
    app = _app(project=None)
    async with _client(app) as client:
        assert (await client.post("/projects/nope/issues/1/play")).status_code == 404
