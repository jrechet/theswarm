"""V2 — the one flow: pick a repo, compose, Play, follow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub
from theswarm.tools import github_app


@pytest.fixture(autouse=True)
def _clean_github_app():
    github_app.reset_state()
    yield
    github_app.reset_state()


@pytest.fixture(autouse=True)
def _isolate_cycle_tracker():
    """The tracker is a process singleton — leave it as we found it."""
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm",
        db=conn,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await conn.close()


def _app_creds():
    github_app._credentials = github_app.GitHubAppCredentials(
        app_id="42", private_key_pem="pem", client_id="Iv1.x",
        client_secret="s", slug="theswarm-jrec",
        html_url="https://github.com/apps/theswarm-jrec",
    )
    github_app._credentials_loaded = True


# ── Home: the picker owns `/` ──────────────────────────────────────────


async def test_root_serves_the_picker_not_a_redirect(web):
    client, _ = web
    r = await client.get("/")
    assert r.status_code == 200
    assert "Pick a repository" in r.text


async def test_home_without_app_offers_to_connect(web):
    client, _ = web
    r = await client.get("/")
    assert "Connect GitHub" in r.text
    assert 'data-testid="repo-list"' not in r.text


@respx.mock
async def test_home_lists_installation_repositories(web, respx_mock):
    client, _ = web
    _app_creds()
    github_app._token, github_app._token_expires_at = "ghs_x", 9e12
    respx_mock.get(
        "https://api.github.com/installation/repositories?per_page=100",
    ).mock(return_value=Response(200, json={"repositories": [
        {"full_name": "jrechet/concert-tour-app",
         "description": "Tour dates and tickets", "private": False,
         "language": "Python"},
    ]}))

    r = await client.get("/")

    assert 'data-testid="repo-list"' in r.text
    assert 'href="/swarm/r/jrechet/concert-tour-app"' in r.text
    assert "Tour dates and tickets" in r.text
    assert "installations/new" in r.text  # add/remove repositories link


async def test_home_keeps_pre_app_registered_projects_reachable(web):
    client, app = web
    from theswarm.application.commands.create_project import (
        CreateProjectCommand,
    )
    await app.state.create_project_handler.handle(
        CreateProjectCommand(project_id="legacy-proj", repo="jrechet/legacy"),
    )

    r = await client.get("/")

    assert 'href="/swarm/r/jrechet/legacy"' in r.text


# ── Repo page: board + auto-registration ───────────────────────────────


async def test_repo_page_registers_the_project_on_first_visit(web):
    client, app = web
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=[])
        r = await client.get("/r/jrechet/concert-tour-app")

    assert r.status_code == 200
    projects = await app.state.list_projects_query.execute()
    assert any(p.repo == "jrechet/concert-tour-app" for p in projects)


async def test_repo_page_groups_issues_by_status(web):
    client, _ = web
    issues = [
        {"number": 7, "title": "Ship the seating map",
         "labels": ["status:ready", "role:dev"]},
        {"number": 9, "title": "Dark mode", "labels": []},
        {"number": 11, "title": "Payment flow",
         "labels": ["status:in-progress"]},
    ]
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=issues)
        r = await client.get("/r/jrechet/concert-tour-app")

    text = r.text
    assert text.index("Building") < text.index("Payment flow")
    assert text.index("Ready") < text.index("Ship the seating map")
    assert text.index("Backlog") < text.index("Dark mode")
    assert text.count("▶") == 3  # every non-building issue gets Play


async def test_repo_page_survives_github_being_down(web):
    client, _ = web
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(
            side_effect=RuntimeError("api.github.com unreachable"),
        )
        r = await client.get("/r/jrechet/concert-tour-app")

    assert r.status_code == 200
    assert "GitHub didn&#39;t answer" in r.text or "GitHub didn't answer" in r.text


# ── Composer: free text → GitHub issue ─────────────────────────────────


async def test_composer_creates_an_issue_from_free_text(web):
    client, _ = web
    with patch("theswarm.tools.github.GitHubClient") as klass:
        create = AsyncMock(return_value={"number": 12})
        klass.return_value.create_issue = create
        r = await client.post(
            "/r/jrechet/concert-tour-app/issues",
            data={"body": "Add a waiting list\nFans join when a show sells out."},
        )

    assert r.status_code == 303
    assert r.headers["location"] == "/swarm/r/jrechet/concert-tour-app"
    create.assert_awaited_once_with(
        title="Add a waiting list",
        body="Fans join when a show sells out.",
        labels=["status:backlog"],
    )


async def test_composer_truncates_a_runaway_title(web):
    client, _ = web
    with patch("theswarm.tools.github.GitHubClient") as klass:
        create = AsyncMock(return_value={"number": 13})
        klass.return_value.create_issue = create
        await client.post(
            "/r/jrechet/concert-tour-app/issues",
            data={"body": "x" * 300},
        )

    assert len(create.await_args.kwargs["title"]) == 80


async def test_composer_ignores_empty_submissions(web):
    client, _ = web
    with patch("theswarm.tools.github.GitHubClient") as klass:
        create = AsyncMock()
        klass.return_value.create_issue = create
        r = await client.post(
            "/r/jrechet/concert-tour-app/issues", data={"body": "   "},
        )

    assert r.status_code == 303
    create.assert_not_awaited()


# ── Play: one click starts a targeted cycle ────────────────────────────


async def test_play_starts_a_cycle_pinned_to_the_issue(web, _isolate_cycle_tracker):
    client, _ = web
    with patch("theswarm.api.run_api_cycle", new=AsyncMock()) as run:
        r = await client.post("/r/jrechet/concert-tour-app/issues/7/play")
        import asyncio
        await asyncio.sleep(0)  # let the created task reach the mock

    assert r.status_code == 303
    assert r.headers["location"].startswith("/swarm/c/")
    cycle_id = r.headers["location"].rsplit("/", 1)[-1]
    record = _isolate_cycle_tracker.get(cycle_id)
    assert record is not None
    assert record.repo == "jrechet/concert-tour-app"
    assert record.issue_number == 7
    assert run.await_args.kwargs["issue_number"] == 7


async def test_running_cycle_shows_the_follow_banner(web, _isolate_cycle_tracker):
    client, _ = web
    from theswarm.api import CycleRequest

    record = _isolate_cycle_tracker.create(
        CycleRequest(repo="jrechet/concert-tour-app", issue_number=7),
    )
    issues = [{"number": 7, "title": "Ship the seating map",
               "labels": ["status:in-progress"]}]
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=issues)
        r = await client.get("/r/jrechet/concert-tour-app")

    assert 'data-testid="running-banner"' in r.text
    assert f"/swarm/c/{record.id}" in r.text
    assert "Follow" in r.text
    assert "▶" not in r.text  # the building issue offers Follow, not Play
