"""V3, M6 — the four behaviours that outlive V1 and V2, on V3 before the
deletion (docs/plans/2026-10-v3-one-product.md): the readiness page, the
memory viewer, the GitHub setup doors, the instance settings.
"""

from __future__ import annotations

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
from theswarm.presentation.web.sse import SSEHub

HTML = {"accept": "text/html"}


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(), db=conn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    await conn.close()


class TestTheReadinessPage:
    async def test_it_wears_the_shell_and_lists_every_check(self, web):
        client, _ = web
        r = await client.get("/health/ready/page", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="readiness"' in r.text and 'data-testid="rail-home"' in r.text
        assert 'data-testid="ready-row" data-check="secret_vault"' in r.text
        assert 'data-testid="readiness-status"' in r.text
        assert "hx-get" not in r.text and "/health/ready" in r.text  # it refreshes itself with fetch, not HTMX


class TestTheMemoryViewer:
    async def test_the_entries_by_category_on_v3(self, web):
        client, _ = web
        entries = [
            {"category": "stack", "content": "FastAPI with aiosqlite", "timestamp": "2026-10-01T07:00:00Z", "confidence": 0.9},
            {"category": "errors", "content": "Never pin dated model ids", "timestamp": "2026-10-02T07:00:00Z"},
        ]
        with patch("theswarm.memory_store.load_entries", new=AsyncMock(return_value=entries)), \
                patch("theswarm.tools.github.GitHubClient"):
            r = await client.get("/r/jrechet/concert-tour-app/memory", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="memory-page"' in r.text and 'data-testid="rail-home"' in r.text
        assert 'data-testid="memory-stack"' in r.text and "FastAPI with aiosqlite" in r.text
        assert 'data-testid="memory-errors"' in r.text and "Mistakes to avoid" in r.text
        assert "2 entries" in r.text and "text-rust" not in r.text  # the V2 aliases are gone from the page

    async def test_an_unreadable_memory_is_said(self, web):
        client, _ = web
        with patch("theswarm.memory_store.load_entries", new=AsyncMock(side_effect=RuntimeError("no token"))), \
                patch("theswarm.tools.github.GitHubClient"):
            r = await client.get("/r/jrechet/concert-tour-app/memory", headers=HTML)
        assert r.status_code == 200 and 'data-testid="memory-error"' in r.text and "no token" in r.text


class TestTheGitHubDoors:
    async def test_the_app_setup_page_on_the_bare_layout(self, web):
        client, _ = web
        with patch("theswarm.presentation.web.routes.github_setup.github_app") as gh:
            gh.load_credentials = AsyncMock(return_value=None)
            r = await client.get("/setup/github-app", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="github-app-setup"' in r.text and 'data-testid="github-app-form"' in r.text
        assert "static/v3/app.css" in r.text and 'data-testid="rail-home"' not in r.text  # a door, no rail

    async def test_the_oauth_setup_page_and_its_form(self, web):
        client, _ = web
        r = await client.get("/setup/github-oauth", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="github-oauth-setup"' in r.text and 'data-testid="github-oauth-form"' in r.text
        assert "/auth/github/callback" in r.text
        r = await client.post("/setup/github-oauth", data={"client_id": "", "client_secret": ""})
        assert r.status_code == 200 and 'data-testid="error"' in r.text


class TestTheInstanceSettings:
    async def test_without_a_vault_the_page_says_so(self, web):
        client, app = web
        app.state.secret_vault = None
        r = await client.get("/settings/instance", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="settings-instance" data-vault="off"' in r.text
        assert 'data-testid="setting" data-key="GITHUB_TOKEN"' in r.text and "SWARM_VAULT_MASTER_KEY" in r.text
        assert 'data-testid="settings-instance-link"' not in r.text and 'aria-current="page"' in r.text
        r = await client.post("/settings/instance/GITHUB_TOKEN", data={"value": "ghp_x"})
        assert r.status_code == 503 and 'data-testid="vault-error"' in r.text

    async def test_the_customers_page_links_to_it(self, web):
        client, _ = web
        r = await client.get("/settings/customers", headers=HTML)
        assert r.status_code == 200 and 'data-testid="settings-instance-link"' in r.text

    async def test_a_value_set_in_the_environment_is_shown_masked(self, web, monkeypatch):
        client, app = web
        app.state.secret_vault = None
        monkeypatch.setenv("SEQ_API_KEY", "LW0ERE2Sawr8RFfqgfYv")
        r = await client.get("/settings/instance", headers=HTML)
        assert 'data-testid="setting" data-key="SEQ_API_KEY" data-set="true"' in r.text
        assert "LW0E…gfYv" in r.text and "LW0ERE2Sawr8RFfqgfYv" not in r.text
