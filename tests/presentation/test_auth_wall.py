"""The dashboard is closed by default; only monitoring stays open.

Issue #38: the production app answered anonymous requests on every route,
including the ones that spend money (POST /api/cycle) and write to GitHub.
The wall is fail-safe: enforced unless SWARM_AUTH_DISABLED is truthy, which
only tests and local dev set (tests/conftest.py does it suite-wide).
"""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web import auth as auth_mod
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.auth import mint_session, verify_session
from theswarm.presentation.web.sse import SSEHub

SECRET = "test-session-secret"
KEY = "test-access-key"


@pytest.fixture(autouse=True)
def _wall_enabled(monkeypatch):
    """Turn the wall ON for this module (the suite-wide default is OFF)."""
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", SECRET)
    monkeypatch.setenv("SWARM_ACCESS_KEY", KEY)
    auth_mod.reset_login_throttle()


@pytest.fixture()
async def client(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await conn.close()


async def _login(client) -> None:
    r = await client.post("/login", data={"access_key": KEY})
    assert r.status_code == 303


# ── Session tokens ─────────────────────────────────────────────────────


def test_session_roundtrip():
    token = mint_session("jrechet", secret=SECRET, ttl_seconds=60)
    assert verify_session(token, secret=SECRET) == "jrechet"


def test_expired_session_is_rejected():
    token = mint_session("jrechet", secret=SECRET, ttl_seconds=-1)
    assert verify_session(token, secret=SECRET) is None


def test_tampered_session_is_rejected():
    token = mint_session("jrechet", secret=SECRET, ttl_seconds=60)
    assert verify_session(token + "x", secret=SECRET) is None
    assert verify_session("garbage", secret=SECRET) is None
    assert verify_session(token, secret="other-secret") is None


# ── Anonymous requests hit the wall ────────────────────────────────────


async def test_anonymous_html_page_redirects_to_login(client):
    r = await client.get("/projects/", headers={"Accept": "text/html"})
    assert r.status_code == 303
    assert r.headers["location"].endswith("/login?next=%2Fprojects%2F")


async def test_anonymous_api_gets_401(client):
    r = await client.get("/api/dashboard")
    assert r.status_code == 401


async def test_anonymous_cannot_start_a_cycle(client):
    """The exact call reproduced from outside in issue #38."""
    r = await client.post("/api/cycle", json={"repo": "a/b"})
    assert r.status_code == 401


async def test_anonymous_htmx_fragment_gets_hx_redirect(client):
    r = await client.get("/fragments/stats", headers={"HX-Request": "true"})
    assert r.status_code == 401
    assert r.headers["HX-Redirect"].endswith("/login")


# ── What stays open, and why ───────────────────────────────────────────


@pytest.mark.parametrize("path", [
    "/health",            # Docker healthcheck — the container dies without it
    "/health/ready",      # readiness probe
])
async def test_monitoring_stays_open(client, path):
    r = await client.get(path)
    assert r.status_code == 200


async def test_login_page_is_reachable(client):
    r = await client.get("/login")
    assert r.status_code == 200
    assert "access_key" in r.text


async def test_webhook_keeps_its_own_hmac_auth(client):
    """The GitHub webhook authenticates via X-Hub-Signature-256, not session."""
    r = await client.post("/webhooks/github", json={})
    assert r.status_code != 303  # not bounced to the login page
    assert r.status_code in (401, 501)  # its own logic answers


async def test_public_demo_short_links_stay_open(client):
    r = await client.get("/d/abc123")
    assert r.status_code in (200, 404)  # not walled, just possibly absent


# ── Logging in ─────────────────────────────────────────────────────────


async def test_wrong_key_is_rejected_without_a_cookie(client):
    r = await client.post("/login", data={"access_key": "wrong"})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers


async def test_right_key_opens_the_dashboard(client):
    await _login(client)
    r = await client.get("/projects/")
    assert r.status_code == 200


async def test_login_redirects_to_next_path(client):
    r = await client.post(
        "/login", data={"access_key": KEY, "next": "/cycles/"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/cycles/"


async def test_next_cannot_be_an_absolute_url(client):
    """Open-redirect guard: next must be an app-relative path."""
    r = await client.post(
        "/login", data={"access_key": KEY, "next": "https://evil.example"},
    )
    assert r.status_code == 303
    assert "evil.example" not in r.headers["location"]


async def test_logout_closes_the_session(client):
    await _login(client)
    r = await client.post("/logout")
    assert r.status_code == 303
    r = await client.get("/projects/", headers={"Accept": "text/html"})
    assert r.status_code == 303  # walled again


async def test_bearer_access_key_allows_api_scripting(client):
    """Ops scripts can call the API with the access key as a Bearer token."""
    r = await client.get(
        "/api/dashboard", headers={"Authorization": f"Bearer {KEY}"},
    )
    assert r.status_code == 200


async def test_login_throttles_after_repeated_failures(client):
    for _ in range(5):
        r = await client.post("/login", data={"access_key": "wrong"})
        assert r.status_code == 401
    r = await client.post("/login", data={"access_key": KEY})
    assert r.status_code == 429  # even the right key waits out the lockout


# ── CSRF: cross-site writes are refused ────────────────────────────────


async def test_cross_site_post_is_refused(client):
    await _login(client)
    r = await client.post(
        "/api/cycle", json={"repo": "a/b"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


async def test_same_origin_post_passes_csrf(client):
    await _login(client)
    r = await client.post(
        "/logout", headers={"Origin": "http://test"},
    )
    assert r.status_code == 303


# ── The kill switch is explicit, never implicit ────────────────────────


async def test_no_access_key_still_walls_but_cannot_login(client, monkeypatch):
    """Losing the env vars must fail CLOSED, not open (the #31 lesson)."""
    monkeypatch.setenv("SWARM_ACCESS_KEY", "")
    r = await client.get("/projects/", headers={"Accept": "text/html"})
    assert r.status_code == 303  # still walled
    r = await client.post("/login", data={"access_key": ""})
    assert r.status_code == 401  # empty key never matches


async def test_disabled_flag_opens_everything(client, monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "1")
    r = await client.get("/projects/")
    assert r.status_code == 200
