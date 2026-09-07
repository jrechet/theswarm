"""GitHub credential detection, board error, and cycle rejection (issue #57).

Fills gaps left by test_v2_flow.py / test_api_routes.py:
- load_credentials() falling back to env when the vault itself is broken,
  and the home page surviving list_installation_repositories() raising.
- the 160-char truncation of a GitHub board error, and that it never
  produces an HTTP error status.
- /api/cycle's synchronous 400/422 rejections, the async allowlist
  rejection surfaced only through the tracker record, and the cancel
  route's 404/409 branches.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.api import CycleRequest, CycleStatus
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


class _BrokenVault:
    """A vault that raises on every read — locked, misconfigured, or down."""

    async def get(self, project_id: str, key: str) -> str:
        raise RuntimeError("vault is locked")


# ── GitHub credential detection ─────────────────────────────────────────


async def test_load_credentials_falls_back_to_env_when_vault_is_broken(
    web, monkeypatch,
):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    github_app.configure(_BrokenVault())

    creds = await github_app.load_credentials()

    assert creds is None


async def test_load_credentials_uses_env_fallback_despite_broken_vault(
    web, monkeypatch,
):
    monkeypatch.setenv("GITHUB_APP_ID", "99")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "env-pem")
    github_app.configure(_BrokenVault())

    creds = await github_app.load_credentials()

    assert creds is not None
    assert creds.app_id == "99"
    assert creds.private_key_pem == "env-pem"


async def test_home_offers_to_connect_when_vault_is_broken_and_no_env(
    web, monkeypatch,
):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    github_app.configure(_BrokenVault())
    client, _ = web

    r = await client.get("/")

    assert r.status_code == 200
    assert "Connect GitHub" in r.text
    assert 'data-testid="repo-list"' not in r.text


async def test_home_survives_installation_repositories_failing(web):
    client, _ = web
    _app_creds()
    with patch(
        "theswarm.tools.github_app.list_installation_repositories",
        new=AsyncMock(side_effect=RuntimeError("GitHub App API rate limited")),
    ), patch(
        "theswarm.tools.github_app.list_user_repositories",
        new=AsyncMock(return_value=[]),
    ):
        r = await client.get("/")

    assert r.status_code == 200
    assert 'data-testid="repo-list"' not in r.text
    # App is configured (creds present) but the repo listing errored, so the
    # picker offers the install flow rather than the "connect GitHub" card.
    assert "No repositories yet" in r.text
    assert "Connect GitHub" not in r.text


# ── Board error ──────────────────────────────────────────────────────────


async def test_repo_page_truncates_a_long_github_error(web):
    client, _ = web
    long_message = "GitHub is unreachable: " + ("x" * 300)
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(
            side_effect=RuntimeError(long_message),
        )
        r = await client.get("/r/jrechet/concert-tour-app")

    assert r.status_code == 200
    assert long_message[:160] in r.text
    assert long_message not in r.text  # the tail past 160 chars is dropped


async def test_repo_page_error_and_empty_board_are_mutually_exclusive(web):
    client, _ = web
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(
            side_effect=RuntimeError("bad credentials"),
        )
        r = await client.get("/r/jrechet/concert-tour-app")

    assert r.status_code == 200
    assert "bad credentials" in r.text
    assert "No open issues" not in r.text


# ── Cycle rejection ──────────────────────────────────────────────────────


async def test_start_cycle_rejects_invalid_json(web):
    client, _ = web
    r = await client.post(
        "/api/cycle", content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


async def test_start_cycle_rejects_a_non_object_body(web):
    client, _ = web
    r = await client.post("/api/cycle", json=["jrechet/concert-tour-app"])
    assert r.status_code == 422


async def test_start_cycle_rejects_missing_repo(web):
    client, _ = web
    r = await client.post("/api/cycle", json={"description": "no repo field"})
    assert r.status_code == 422
    assert any(
        err.get("loc") == ["repo"] for err in r.json()["detail"]
    )


async def test_start_cycle_accepts_but_later_fails_a_disallowed_repo(
    web, _isolate_cycle_tracker,
):
    client, app = web
    app.state.allowed_repos = ["jrechet/allowed-only"]

    r = await client.post("/api/cycle", json={"repo": "someone/not-allowed"})
    assert r.status_code == 200
    cycle_id = r.json()["cycle_id"]
    assert r.json()["status"] == CycleStatus.QUEUED.value

    await asyncio.sleep(0)  # let the background task run to the allowlist gate

    record = _isolate_cycle_tracker.get(cycle_id)
    assert record.status == CycleStatus.FAILED
    assert "not in allowed list" in record.error


async def test_cancel_unknown_cycle_is_404(web):
    client, _ = web
    r = await client.post("/api/cycle/does-not-exist/cancel")
    assert r.status_code == 404


async def test_cancel_a_finished_cycle_is_409(web, _isolate_cycle_tracker):
    client, _ = web
    record = _isolate_cycle_tracker.create(
        CycleRequest(repo="jrechet/concert-tour-app"),
    )
    _isolate_cycle_tracker.update_status(record.id, CycleStatus.COMPLETED)

    r = await client.post(f"/api/cycle/{record.id}/cancel")

    assert r.status_code == 409
    assert "completed" in r.json()["detail"]


async def test_theater_404s_for_an_unknown_cycle(web):
    client, _ = web
    r = await client.get("/c/does-not-exist")
    assert r.status_code == 404


async def test_theater_stage_404s_for_an_unknown_cycle(web):
    client, _ = web
    r = await client.get("/c/does-not-exist/stage")
    assert r.status_code == 404
