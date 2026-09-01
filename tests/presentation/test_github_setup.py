"""Manifest-flow setup and GitHub OAuth sign-in."""

from __future__ import annotations

import json

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

FWD = {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "bots.jrec.fr"}


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
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    yield
    github_app.reset_state()


@pytest.fixture()
def vault():
    v = _FakeVault()
    github_app.configure(v)
    return v


@pytest.fixture()
async def client(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await conn.close()


def _stored_creds(monkeypatch=None):
    github_app._credentials = github_app.GitHubAppCredentials(
        app_id="42", private_key_pem="pem", client_id="Iv1.x",
        client_secret="sec", slug="theswarm-jrec",
        html_url="https://github.com/apps/theswarm-jrec",
    )
    github_app._credentials_loaded = True


# ── The setup page ─────────────────────────────────────────────────────


async def test_setup_page_offers_the_manifest_form(client, vault):
    r = await client.get("/setup/github-app", headers=FWD)
    assert r.status_code == 200
    assert 'action="https://github.com/settings/apps/new"' in r.text


async def test_manifest_points_back_at_this_instance(client, vault):
    r = await client.get("/setup/github-app", headers=FWD)
    start = r.text.index('id="manifest" value="') + len('id="manifest" value="')
    raw = r.text[start:r.text.index('"', start)]
    manifest = json.loads(raw.replace("&#34;", '"').replace("&quot;", '"'))
    assert manifest["redirect_url"] == (
        "https://bots.jrec.fr/swarm/setup/github-app/callback"
    )
    assert manifest["callback_urls"] == [
        "https://bots.jrec.fr/swarm/auth/github/callback",
    ]
    assert manifest["hook_attributes"]["active"] is False


async def test_manifest_asks_only_for_repo_scoped_permissions(client, vault):
    r = await client.get("/setup/github-app", headers=FWD)
    start = r.text.index('id="manifest" value="') + len('id="manifest" value="')
    raw = r.text[start:r.text.index('"', start)]
    manifest = json.loads(raw.replace("&#34;", '"').replace("&quot;", '"'))
    assert manifest["default_permissions"] == {
        "contents": "write", "issues": "write", "pull_requests": "write",
        "checks": "write", "metadata": "read",
    }
    assert manifest["public"] is False


async def test_setup_page_shows_install_link_once_connected(client, vault):
    _stored_creds()
    r = await client.get("/setup/github-app", headers=FWD)
    assert "installations/new" in r.text
    assert "theswarm-jrec" in r.text


# ── The callback stores what GitHub sends back ─────────────────────────


@respx.mock
async def test_callback_converts_the_code_and_stores_credentials(
    client, vault, respx_mock,
):
    respx_mock.post(
        "https://api.github.com/app-manifest/one-time-code/conversions",
    ).mock(return_value=Response(201, json={
        "id": 4242, "pem": "-----BEGIN RSA PRIVATE KEY-----fake",
        "client_id": "Iv1.new", "client_secret": "s3cret",
        "webhook_secret": "wh", "slug": "theswarm-jrec",
        "html_url": "https://github.com/apps/theswarm-jrec",
    }))

    r = await client.get(
        "/setup/github-app/callback?code=one-time-code", headers=FWD,
    )

    assert r.status_code == 303
    assert r.headers["location"].endswith("/setup/github-app?created=1")
    assert vault.data[(github_app.VAULT_PROJECT_ID, "app_id")] == "4242"
    assert vault.data[(github_app.VAULT_PROJECT_ID, "client_secret")] == "s3cret"


@respx.mock
async def test_callback_survives_a_burned_code(client, vault, respx_mock):
    respx_mock.post(
        "https://api.github.com/app-manifest/stale/conversions",
    ).mock(return_value=Response(404, json={"message": "Not Found"}))

    r = await client.get("/setup/github-app/callback?code=stale", headers=FWD)

    assert r.status_code == 502
    assert "Start over" in r.text


# ── GitHub OAuth sign-in ───────────────────────────────────────────────


async def test_oauth_start_redirects_to_github(client, vault):
    _stored_creds()
    r = await client.get("/auth/github", headers=FWD)
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=Iv1.x" in location
    assert "state=" in location


async def test_oauth_start_without_app_bounces_to_login(client, vault):
    r = await client.get("/auth/github", headers=FWD)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


@respx.mock
async def test_owner_gets_a_session(client, vault, respx_mock, monkeypatch):
    monkeypatch.setenv("SWARM_OWNER_LOGIN", "jrechet")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s")
    _stored_creds()
    from theswarm.presentation.web.auth import mint_session
    state = mint_session("oauth-state", ttl_seconds=600)
    respx_mock.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "gho_user"}),
    )
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "jrechet"}),
    )

    r = await client.get(
        f"/auth/github/callback?code=c&state={state}", headers=FWD,
    )

    assert r.status_code == 303
    assert "swarm_session=" in r.headers.get("set-cookie", "")


@respx.mock
async def test_anyone_else_is_refused(client, vault, respx_mock, monkeypatch):
    monkeypatch.setenv("SWARM_OWNER_LOGIN", "jrechet")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s")
    _stored_creds()
    from theswarm.presentation.web.auth import mint_session
    state = mint_session("oauth-state", ttl_seconds=600)
    respx_mock.post("https://github.com/login/oauth/access_token").mock(
        return_value=Response(200, json={"access_token": "gho_intruder"}),
    )
    respx_mock.get("https://api.github.com/user").mock(
        return_value=Response(200, json={"login": "intruder"}),
    )

    r = await client.get(
        f"/auth/github/callback?code=c&state={state}", headers=FWD,
    )

    assert r.status_code == 303
    assert "belongs+to+someone+else" in r.headers["location"]
    assert "set-cookie" not in r.headers


async def test_forged_state_is_refused(client, vault, monkeypatch):
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s")
    _stored_creds()
    r = await client.get(
        "/auth/github/callback?code=c&state=forged", headers=FWD,
    )
    assert r.status_code == 303
    assert "expired" in r.headers["location"]


# ── The login page advertises the right doors ──────────────────────────


async def test_login_page_hides_github_until_configured(client, vault):
    r = await client.get("/login")
    assert "Sign in with GitHub" not in r.text


async def test_login_page_shows_github_once_configured(client, vault):
    _stored_creds()
    r = await client.get("/login")
    assert "Sign in with GitHub" in r.text
