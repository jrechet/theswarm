"""DevOps D1 on the product: the Ops card on the owner's home, `/api/devops`,
the refresh — the owner's only; a member never sees the pipeline.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.agents.devops import Finding, OpsReport
from theswarm.application.events.bus import EventBus
from theswarm.application.services.ops_watch import OpsWatch
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.auth import SESSION_COOKIE
from theswarm.presentation.web.sse import SSEHub

KEY = "k-ops-test"
HTML = {"accept": "text/html"}
NOW = datetime(2026, 10, 7, 14, 5, tzinfo=timezone.utc)
STALE = Finding("ci_slot", "CI slot", "bad", "stale: slot1 held by runner-areza (jrechet/areza) for 150 min — past the 180 min rule", "")
FINE = Finding("claude", "Claude", "ok", "credentials and window fine")


def _report(*findings) -> OpsReport:
    return OpsReport(tuple(findings), read_at=NOW, stack="jrec.fr · github-actions · ghcr.io · docker-swarm")


@pytest.fixture(autouse=True)
def _wall(monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("SWARM_ACCESS_KEY", KEY)


@pytest.fixture()
async def app(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(), db=conn)
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


def _home(client):
    with patch("theswarm.presentation.web.routes.v2.github_app") as gh:
        gh.load_credentials = AsyncMock(return_value=None)
        gh.list_user_repositories = AsyncMock(return_value=[])
        gh.oauth_client = AsyncMock(return_value=object())
        return client.get("/", headers=HTML)


def _watch(app, *reports):
    reports = list(reports)

    async def gather():
        return reports.pop(0) if len(reports) > 1 else reports[0]

    app.state.ops_watch = OpsWatch(gather, clock=lambda: NOW)
    return app.state.ops_watch


class TestTheOpsCard:
    async def test_the_suite_declares_no_stack(self, app, owner):
        assert app.state.ops_watch is None
        r = await _home(owner)
        assert r.status_code == 200 and 'data-testid="ops-card"' not in r.text

    async def test_the_card_shows_the_last_report(self, app, owner):
        watch = _watch(app, _report(STALE, FINE))
        r = await _home(owner)
        assert 'data-testid="ops-card" data-status="unknown"' in r.text and "reading…" in r.text  # nothing read yet
        await watch.refresh()
        r = await _home(owner)
        assert 'data-testid="ops-card" data-status="bad"' in r.text and "Something is wrong" in r.text
        assert 'data-testid="ops-row" data-key="ci_slot" data-status="bad"' in r.text and "past the 180 min rule" in r.text
        assert 'data-testid="ops-row" data-key="claude" data-status="ok"' in r.text
        assert "jrec.fr · github-actions" in r.text and "read 14:05 UTC" in r.text
        assert 'data-testid="ops-refresh"' in r.text

    async def test_a_failed_read_is_said_on_the_card(self, app, owner):
        async def gather():
            raise RuntimeError("ssh timed out")

        app.state.ops_watch = OpsWatch(gather, clock=lambda: NOW)
        await app.state.ops_watch.refresh()
        r = await _home(owner)
        assert 'data-testid="ops-error"' in r.text and "ssh timed out" in r.text

    async def test_the_api_and_the_refresh(self, app, owner):
        _watch(app, _report(FINE), _report(STALE, FINE))
        r = await owner.get("/api/devops")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["findings"][0]["key"] == "claude" and body["stack"].startswith("jrec.fr")
        r = await owner.post("/api/devops/refresh")
        assert r.status_code == 200 and r.json()["status"] == "bad"
        r = await owner.post("/ops/refresh")
        assert r.status_code == 303 and r.headers["location"].endswith("/#ops")

    async def test_without_a_stack_the_api_says_so(self, owner):
        r = await owner.get("/api/devops")
        assert r.status_code == 404 and "not configured" in r.json()["detail"]
        r = await owner.post("/ops/refresh")
        assert r.status_code == 303

    async def test_a_member_never_sees_the_pipeline(self, app, owner):
        _watch(app, _report(STALE))
        r = await owner.post("/settings/customers", data={"name": "TLphone"})
        assert r.status_code == 303
        r = await owner.post("/settings/customers/tlphone/members", data={"email": "nadia@tlphone.fr", "display_name": "Nadia"})
        link = re.search(r'value="(http://test/invite/[^"]+)"', r.text).group(1).replace("http://test", "")
        async with _client(app) as nadia:
            r = await nadia.get(link)
            assert r.status_code == 303 and SESSION_COOKIE in nadia.cookies
            r = await nadia.get("/api/devops", headers={"accept": "application/json"})
            assert r.status_code == 403
            r = await nadia.post("/ops/refresh", headers=HTML)
            assert r.status_code == 403
            r = await nadia.get("/c/tlphone", headers=HTML)
            assert r.status_code == 200 and 'data-testid="ops-card"' not in r.text
