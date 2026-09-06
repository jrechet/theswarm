"""Tous mes projets, and Sign in with GitHub without the manifest flow."""

from __future__ import annotations

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


class _FakeVault:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    async def set(self, project_id, key, value):
        self.data[(project_id, key)] = value

    async def get(self, project_id, key):
        return self.data.get((project_id, key))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    github_app.reset_state()
    for var in ("GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY",
                "GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    yield
    github_app.reset_state()


@pytest.fixture()
def vault():
    v = _FakeVault()
    github_app.configure(v)
    return v


@pytest.fixture()
async def client(tmp_path):
    conn = await init_db(str(tmp_path / "t.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await conn.close()


def _repo(full_name, pushed, private=False, language="Python"):
    return {"full_name": full_name, "description": "", "private": private,
            "language": language, "pushed_at": pushed}


# ── Tous mes projets ───────────────────────────────────────────────────


@respx.mock
async def test_user_repositories_follow_pagination(respx_mock, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_owner")
    first = "https://api.github.com/user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator,organization_member"
    respx_mock.get(first).mock(return_value=Response(
        200, json=[_repo("jrechet/a", "2026-09-01T00:00:00Z")],
        headers={"Link": '<https://api.github.com/user/repos?page=2>; rel="next"'},
    ))
    respx_mock.get("https://api.github.com/user/repos?page=2").mock(
        return_value=Response(200, json=[_repo("jrechet/b", "2026-08-01T00:00:00Z")]),
    )
    repos = await github_app.list_user_repositories()
    assert [r["full_name"] for r in repos] == ["jrechet/a", "jrechet/b"]


async def test_no_token_means_no_call_and_no_repos():
    assert await github_app.list_user_repositories() == []


@respx.mock
async def test_home_lists_every_repo_the_token_sees(client, vault, respx_mock, monkeypatch):
    """No App configured: the owner's token alone fills the picker."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_owner")
    respx_mock.get(url__regex=r"https://api\.github\.com/user/repos.*").mock(
        return_value=Response(200, json=[
            _repo("jrechet/yakoi", "2026-09-05T10:00:00Z", private=True),
            _repo("jrechet/vraak", "2026-09-04T10:00:00Z", private=True),
        ]),
    )
    r = await client.get("/")
    assert r.status_code == 200
    assert 'href="/swarm/r/jrechet/yakoi"' in r.text
    assert 'href="/swarm/r/jrechet/vraak"' in r.text
    assert "2 repositories" in r.text
    assert "Connect GitHub" not in r.text  # the list is the page now


@respx.mock
async def test_home_orders_by_last_push_and_dedups(client, vault, respx_mock, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_owner")
    respx_mock.get(url__regex=r"https://api\.github\.com/user/repos.*").mock(
        return_value=Response(200, json=[
            _repo("jrechet/old", "2025-01-01T00:00:00Z"),
            _repo("jrechet/new", "2026-09-05T00:00:00Z"),
            _repo("jrechet/new", "2026-09-05T00:00:00Z"),
        ]),
    )
    r = await client.get("/")
    assert r.text.index("jrechet/r/jrechet/new".replace("jrechet/r/", "r/")) < r.text.index("r/jrechet/old")
    assert r.text.count('href="/swarm/r/jrechet/new"') == 1


async def test_home_without_any_source_still_offers_setup(client, vault):
    r = await client.get("/")
    assert r.status_code == 200
    assert "Connect GitHub" in r.text


# ── OAuth client resolution ────────────────────────────────────────────


async def test_oauth_client_prefers_the_app_then_vault_then_env(vault, monkeypatch):
    assert await github_app.oauth_client() is None
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "env-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "env-secret")
    assert await github_app.oauth_client() == ("env-id", "env-secret")
    await github_app.store_oauth_client("vault-id", "vault-secret")
    assert await github_app.oauth_client() == ("vault-id", "vault-secret")
    github_app._credentials = github_app.GitHubAppCredentials(
        app_id="1", private_key_pem="pem", client_id="app-id", client_secret="app-secret",
    )
    github_app._credentials_loaded = True
    assert await github_app.oauth_client() == ("app-id", "app-secret")


# ── The one-time settings page ─────────────────────────────────────────


async def test_setup_page_shows_exactly_what_to_enter_on_github(client, vault):
    r = await client.get("/setup/github-oauth", headers={
        "X-Forwarded-Proto": "https", "X-Forwarded-Host": "bots.jrec.fr",
    })
    assert r.status_code == 200
    assert "https://bots.jrec.fr/swarm/auth/github/callback" in r.text
    assert "settings/applications/new" in r.text


async def test_saving_the_client_stores_it_in_the_vault(client, vault):
    r = await client.post("/setup/github-oauth", data={
        "client_id": "Iv1.abc", "client_secret": "s3cret",
    })
    assert r.status_code == 303
    assert vault.data[(github_app.VAULT_OAUTH_PROJECT_ID, "client_id")] == "Iv1.abc"
    assert vault.data[(github_app.VAULT_OAUTH_PROJECT_ID, "client_secret")] == "s3cret"


async def test_empty_submission_is_refused(client, vault):
    r = await client.post("/setup/github-oauth", data={"client_id": "x", "client_secret": " "})
    assert r.status_code == 200
    assert "Both the client ID" in r.text
    assert not vault.data


async def test_login_offers_github_once_an_oauth_client_exists(client, vault):
    assert "Sign in with GitHub" not in (await client.get("/login")).text
    await github_app.store_oauth_client("Iv1.abc", "s3cret")
    assert "Sign in with GitHub" in (await client.get("/login")).text


async def test_oauth_start_works_with_a_plain_oauth_app(client, vault):
    await github_app.store_oauth_client("Iv1.abc", "s3cret")
    r = await client.get("/auth/github", headers={
        "X-Forwarded-Proto": "https", "X-Forwarded-Host": "bots.jrec.fr",
    })
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=Iv1.abc" in loc and "scope=read%3Auser" in loc
