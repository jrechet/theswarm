"""Settings → Agents, the page: the owner sees each persona's Claude and what it
runs on, sets a model and an effort per persona or for all five at once, puts
them back on the instance's default; a member never reaches it.
"""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository, init_db
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.auth import SESSION_COOKIE
from theswarm.presentation.web.sse import SSEHub

KEY = "k-agents-test"
HTML = {"accept": "text/html"}


@pytest.fixture(autouse=True)
def _wall(monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("SWARM_ACCESS_KEY", KEY)
    monkeypatch.setenv("SWARM_CLAUDE_MODEL", "sonnet")


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


def _row(html: str, persona: str) -> str:
    m = re.search(rf'data-testid="agent-row" data-persona="{persona}" data-set="(\w+)">(.*?)</select>\s*</label>\s*</div>', html, re.S)
    return (m.group(1), m.group(2)) if m else (None, "")


class TestThePage:
    async def test_five_personas_on_the_instance_s_default(self, owner):
        r = await owner.get("/settings/agents", headers=HTML)
        assert r.status_code == 200 and 'data-testid="settings-agents"' in r.text
        assert re.findall(r'data-testid="agent-row" data-persona="(\w+)"', r.text) == ["po", "techlead", "dev", "qa", "devops"]
        assert r.text.count("Runs on Sonnet · Claude Code&#39;s effort (the instance&#39;s default)") == 5
        assert 'data-testid="settings-agents-link"' in (await owner.get("/settings/customers", headers=HTML)).text

    async def test_a_model_and_an_effort_per_persona(self, app, owner):
        r = await owner.post("/settings/agents", data={"dev-model": "opus", "dev-effort": "high", "qa-model": "haiku", "qa-effort": "low",
                                                       "po-model": "", "po-effort": ""})
        assert r.status_code == 303 and r.headers["location"].endswith("/settings/agents?saved=1")
        assert await app.state.agent_settings.effective() == {"dev": ("opus", "high"), "qa": ("haiku", "low")}
        page = (await owner.get("/settings/agents?saved=1", headers=HTML)).text
        assert 'data-testid="agents-saved"' in page
        state, body = _row(page, "dev")
        assert state == "true" and "Runs on Opus · High effort" in body and '<option value="opus" selected>' in body
        assert _row(page, "po")[0] == "false"

    async def test_an_effort_alone_is_on_the_instance_s_model_and_all_five_at_once(self, app, owner):
        await owner.post("/settings/agents", data={"techlead-model": "", "techlead-effort": "max"})
        assert await app.state.agent_settings.effective() == {"techlead": ("sonnet", "max")}
        await owner.post("/settings/agents", data={"apply-all": "1", "all-model": "opus", "all-effort": "high"})
        assert await app.state.agent_settings.effective() == {p: ("opus", "high") for p in ("po", "techlead", "dev", "qa", "devops")}
        await owner.post("/settings/agents", data={"apply-all": "1", "all-model": "", "all-effort": ""})
        assert await app.state.agent_settings.effective() == {}

    async def test_a_choice_the_page_does_not_offer_is_refused(self, app, owner):
        r = await owner.post("/settings/agents", data={"dev-model": "gpt-5", "dev-effort": "high"}, headers=HTML)
        assert r.status_code == 400 and 'data-testid="agents-error"' in r.text and "gpt-5" in r.text
        assert await app.state.agent_settings.effective() == {}

    async def test_a_member_never_reaches_it(self, app, owner):
        r = await owner.post("/settings/customers", data={"name": "TLphone"})
        r = await owner.post("/settings/customers/tlphone/members", data={"email": "nadia@tlphone.fr", "display_name": "Nadia"})
        link = re.search(r'value="(http://test/invite/[^"]+)"', r.text).group(1).replace("http://test", "")
        async with _client(app) as nadia:
            r = await nadia.get(link)
            assert r.status_code == 303 and SESSION_COOKIE in nadia.cookies
            assert (await nadia.get("/settings/agents", headers=HTML)).status_code == 403
            assert (await nadia.post("/settings/agents", data={"dev-model": "opus"}, headers=HTML)).status_code == 403
        assert await app.state.agent_settings.effective() == {}
