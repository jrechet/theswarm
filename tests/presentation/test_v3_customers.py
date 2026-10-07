"""V3, M2 — customers and members (docs/plans/2026-10-v3-one-product.md).

The owner creates a customer from Settings, gives it a repository, invites
a person by email: the invitation is a link shown once. Opening it signs
the member in to their customer and nothing else — every other page is
refused, a revoked member is sent to the door. The first customer is real:
TLphone, project espace client (jrechet/espace-client) — the owner,
2026-10-06.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.auth import SESSION_COOKIE
from theswarm.presentation.web.sse import SSEHub

KEY = "k-tlphone-test"
SECRET = "s" * 32
HTML = {"accept": "text/html"}
JSON = {"accept": "application/json"}
REPO = "jrechet/espace-client"


@pytest.fixture(autouse=True)
def _wall(monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", SECRET)
    monkeypatch.setenv("SWARM_ACCESS_KEY", KEY)
    monkeypatch.delenv("EXTERNAL_URL", raising=False)


@pytest.fixture()
async def app(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), db=conn,
    )
    yield app
    await conn.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture()
async def owner(app):
    async with _client(app) as client:
        r = await client.post("/login", data={"access_key": KEY})
        assert r.status_code == 303
        yield client


@pytest.fixture()
async def visitor(app):
    async with _client(app) as client:
        yield client


def _home(client):
    """The owner's home with GitHub stubbed out."""
    with patch("theswarm.presentation.web.routes.v2.github_app") as gh:
        gh.load_credentials = AsyncMock(return_value=None)
        gh.list_user_repositories = AsyncMock(return_value=[])
        gh.oauth_client = AsyncMock(return_value=object())
        return client.get("/", headers=HTML)


async def _tlphone(owner) -> str:
    """TLphone with espace-client, as the owner makes them; returns the slug."""
    r = await owner.post("/settings/customers", data={"name": "TLphone"})
    assert r.status_code == 303 and r.headers["location"].endswith("/settings/customers/tlphone")
    r = await owner.post("/settings/customers/tlphone/projects", data={"full_name": REPO})
    assert r.status_code == 303
    return "tlphone"


async def _invite(owner, slug: str, email: str = "nadia@tlphone.fr", name: str = "Nadia") -> str:
    r = await owner.post(f"/settings/customers/{slug}/members", data={"email": email, "display_name": name})
    assert r.status_code == 200, r.text[:300]
    match = re.search(r'data-testid="invitation-url"\s+class="[^"]*"\s+value="([^"]+)"', r.text) or \
        re.search(r'value="(http://test/invite/[^"]+)"', r.text)
    assert match, "the invitation link is shown"
    return match.group(1).replace("http://test", "")


# ── The owner's side ─────────────────────────────────────────────────


class TestSettings:
    async def test_settings_opens_on_customers(self, owner):
        r = await owner.get("/settings")
        assert r.status_code == 303 and r.headers["location"].endswith("/settings/customers")
        r = await owner.get("/settings/customers", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="settings-customers"' in r.text
        assert 'data-slug="internal"' in r.text  # Internal exists from the migration

    async def test_the_owner_creates_tlphone_and_gives_it_espace_client(self, owner):
        slug = await _tlphone(owner)
        r = await owner.get(f"/settings/customers/{slug}", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="settings-customer" data-slug="tlphone"' in r.text
        assert REPO in r.text and 'data-testid="customer-project"' in r.text
        r = await owner.get("/settings/customers", headers=HTML)
        assert 'data-slug="tlphone"' in r.text and REPO in r.text

    async def test_the_rail_lists_customers_and_their_projects(self, owner):
        await _tlphone(owner)
        r = await _home(owner)
        assert r.status_code == 200
        assert 'data-testid="rail-customer"' in r.text and ">TLphone<" in r.text
        assert f'href="/r/{REPO}"' in r.text
        assert 'data-testid="rail-settings"' in r.text

    async def test_a_nameless_customer_is_refused(self, owner):
        r = await owner.post("/settings/customers", data={"name": "   "})
        assert r.status_code == 400 and 'data-testid="error"' in r.text

    async def test_a_cycle_shaped_name_gets_a_safe_slug(self, owner):
        r = await owner.post("/settings/customers", data={"name": "deadbeefcafe"})
        assert r.headers["location"].endswith("/settings/customers/deadbeefcafe-c")

    async def test_a_bad_repository_name_is_refused(self, owner):
        slug = await _tlphone(owner)
        r = await owner.post(f"/settings/customers/{slug}/projects", data={"full_name": "not a repo"})
        assert r.status_code == 400 and "Not a repository name" in r.text

    async def test_the_owner_opens_a_customer_s_page(self, owner):
        slug = await _tlphone(owner)
        r = await owner.get(f"/c/{slug}", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="customer-page" data-slug="tlphone"' in r.text
        assert f'href="/r/{REPO}"' in r.text  # the owner's links go to the project
        assert "What this customer's members see" in r.text

    async def test_an_unknown_customer_is_404(self, owner):
        r = await owner.get("/c/nobody", headers=HTML)
        assert r.status_code == 404

    async def test_a_cycle_id_still_reaches_the_theater_for_the_owner(self, owner):
        r = await owner.get("/c/0123456789ab", headers=HTML)
        assert r.status_code != 403
        assert 'data-testid="customer-page"' not in r.text and 'data-testid="refused"' not in r.text


class TestInvitations:
    async def test_the_link_is_shown_once(self, owner):
        slug = await _tlphone(owner)
        link = await _invite(owner, slug)
        assert link.startswith("/invite/") and len(link) > 30
        r = await owner.get(f"/settings/customers/{slug}", headers=HTML)
        assert 'data-testid="invitation"' not in r.text  # never shown again
        assert 'data-testid="member" data-state="invited"' in r.text and "Nadia" in r.text

    async def test_the_link_names_the_instance_s_public_address(self, owner, monkeypatch):
        monkeypatch.setenv("EXTERNAL_URL", "https://bots.jrec.fr")
        slug = await _tlphone(owner)
        r = await owner.post(f"/settings/customers/{slug}/members", data={"email": "nadia@tlphone.fr"})
        assert 'value="https://bots.jrec.fr/invite/' in r.text

    async def test_a_bad_email_is_refused(self, owner):
        slug = await _tlphone(owner)
        r = await owner.post(f"/settings/customers/{slug}/members", data={"email": "nadia"})
        assert r.status_code == 400 and "not an email" in r.text

    async def test_a_spent_or_wrong_link_goes_to_the_door(self, owner, visitor):
        slug = await _tlphone(owner)
        link = await _invite(owner, slug)
        r = await visitor.get(link)
        assert r.status_code == 303 and r.headers["location"].endswith("/c/tlphone")
        again = _client(owner._transport.app)
        async with again:
            r = await again.get(link)
            assert r.status_code == 303 and "/login?error=" in r.headers["location"]
            r = await again.get("/invite/not-a-token")
            assert r.status_code == 303 and "/login?error=" in r.headers["location"]


# ── The member's side ────────────────────────────────────────────────


class TestAMember:
    async def _nadia(self, owner, visitor) -> str:
        slug = await _tlphone(owner)
        link = await _invite(owner, slug)
        r = await visitor.get(link)
        assert r.status_code == 303 and SESSION_COOKIE in visitor.cookies
        return slug

    async def test_sees_tlphone_and_nothing_else(self, owner, visitor):
        slug = await self._nadia(owner, visitor)

        r = await visitor.get(f"/c/{slug}", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="customer-page" data-slug="tlphone"' in r.text
        assert "espace-client" in r.text and "Signed in as Nadia" in r.text
        assert 'data-testid="rail-member-customer"' in r.text and ">TLphone<" in r.text
        assert 'data-testid="rail-settings"' not in r.text and 'data-testid="claude-chip"' not in r.text
        assert f'href="/r/{REPO}"' not in r.text  # no project page for a member yet
        assert 'data-testid="rail-customers"' in r.text and 'href="/c/tlphone"' in r.text

        r = await visitor.get("/", headers=HTML)
        assert r.status_code == 303 and r.headers["location"].endswith("/c/tlphone")

        for path in (f"/r/{REPO}", "/c/internal", "/settings/customers", "/c/0123456789ab", "/dashboard"):
            r = await visitor.get(path, headers=HTML)
            assert r.status_code == 403, path
            assert 'data-testid="refused"' in r.text, path
        r = await visitor.get("/api/cycles", headers=JSON)
        assert r.status_code == 403 and r.json()["detail"].startswith("This page belongs")

    async def test_the_owner_sees_the_member_as_active(self, owner, visitor):
        slug = await self._nadia(owner, visitor)
        await visitor.get(f"/c/{slug}", headers=HTML)
        r = await owner.get(f"/settings/customers/{slug}", headers=HTML)
        assert 'data-testid="member" data-state="active"' in r.text and "seen " in r.text

    async def test_revoked_means_the_door(self, owner, visitor):
        slug = await self._nadia(owner, visitor)
        r = await owner.get(f"/settings/customers/{slug}", headers=HTML)
        member_id = re.search(r'/members/([0-9a-f]+)/revoke', r.text).group(1)
        r = await owner.post(f"/settings/customers/{slug}/members/{member_id}/revoke")
        assert r.status_code == 303

        r = await visitor.get(f"/c/{slug}", headers=HTML)
        assert r.status_code == 303 and "Your+access+has+ended" in r.headers["location"]
        assert "swarm_session=" in r.headers.get("set-cookie", "") and ('Max-Age=0' in r.headers["set-cookie"] or "expires" in r.headers["set-cookie"].lower())

        r = await owner.get(f"/settings/customers/{slug}", headers=HTML)
        assert 'data-state="revoked"' in r.text
