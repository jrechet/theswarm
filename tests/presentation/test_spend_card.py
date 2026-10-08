"""The owner's spend view on the product (docs/plans/2026-10-v3-one-product.md):
the home's Spend card — this month and last per customer, the alerts the rows
hold — `/api/spend`, and the chat alert when a cycle finishes. A customer
never sees a cost: the member's pages carry none of it.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.services.spend import month_start
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import CycleCompleted
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.auth import SESSION_COOKIE
from theswarm.presentation.web.sse import SSEHub

KEY = "k-spend-test"
HTML = {"accept": "text/html"}
REPO = "jrechet/espace-client"
NOW = datetime.now(timezone.utc)
LAST_MONTH = month_start(NOW) - timedelta(days=3)  # always last month
_n = iter(range(1, 10_000))


@pytest.fixture(autouse=True)
def _wall(monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("SWARM_ACCESS_KEY", KEY)
    monkeypatch.delenv("EXTERNAL_URL", raising=False)


@pytest.fixture()
async def rig(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    bus = EventBus()
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), bus, SSEHub(), db=conn)
    yield app, bus
    await conn.close()


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture()
async def owner(rig):
    async with _client(rig[0]) as client:
        r = await client.post("/login", data={"access_key": KEY})
        assert r.status_code == 303
        yield client


def _home(client):
    with patch("theswarm.presentation.web.routes.common.github_app") as gh:
        gh.load_credentials = AsyncMock(return_value=None)
        gh.list_user_repositories = AsyncMock(return_value=[])
        gh.oauth_client = AsyncMock(return_value=object())
        return client.get("/", headers=HTML)


async def _cycle(app, cost, when, project=REPO, status=CycleStatus.COMPLETED):
    await app.state.cycle_repo.save(Cycle(
        id=CycleId(f"{next(_n):012x}"), project_id=project, status=status, triggered_by="web",
        started_at=when, completed_at=when, total_cost_usd=cost, prs_merged=(1,) if status == CycleStatus.COMPLETED else (),
    ))


async def _tlphone(owner) -> None:
    r = await owner.post("/settings/customers", data={"name": "TLphone"})
    assert r.status_code == 303
    r = await owner.post("/settings/customers/tlphone/projects", data={"full_name": REPO})
    assert r.status_code == 303


async def _history(app):
    """Five ordinary cycles last month ($2 each) and a dear one a few minutes ago."""
    for i in range(5):
        await _cycle(app, 2.0, LAST_MONTH - timedelta(days=i))
    await _cycle(app, 9.4, NOW - timedelta(minutes=10))
    await _cycle(app, 1.5, NOW - timedelta(minutes=30), project="someone/unregistered")


class TestTheCard:
    async def test_nothing_spent_nothing_shown(self, rig, owner):
        r = await _home(owner)
        assert r.status_code == 200 and 'data-testid="spend-card"' not in r.text

    async def test_per_customer_the_total_and_the_dear_cycle(self, rig, owner):
        app, _ = rig
        await _tlphone(owner)
        await _history(app)
        r = await _home(owner)
        assert r.status_code == 200 and 'data-testid="spend-card"' in r.text
        rows = re.findall(r'data-testid="spend-row" data-customer="([0-9a-f]+|internal)">(.*?)</tr>', r.text, re.S)
        row = next(body for _, body in rows if "TLphone" in body)
        assert "$9.40" in row and "$10.00" in row  # this month, last month
        assert 'data-testid="spend-row" data-customer="internal"' in r.text and "$1.50" in r.text
        assert 'data-testid="spend-total"' in r.text and "$10.90" in r.text
        alert = re.search(r'data-testid="spend-alert" data-kind="dear" data-level="warn">(.*?)</div>', r.text, re.S).group(1)
        assert "A dear cycle on espace-client" in alert and "$9.40, against $2.00 usually" in alert

    async def test_a_member_s_pages_carry_no_spend(self, rig, owner):
        app, _ = rig
        await _tlphone(owner)
        await _history(app)
        r = await owner.post("/settings/customers/tlphone/members", data={"email": "nadia@tlphone.fr", "display_name": "Nadia"})
        link = re.search(r'value="(http://test/invite/[^"]+)"', r.text).group(1).replace("http://test", "")
        async with _client(app) as nadia:
            r = await nadia.get(link)
            assert r.status_code == 303 and SESSION_COOKIE in nadia.cookies
            page = await nadia.get("/c/tlphone", headers=HTML)
            assert page.status_code == 200 and 'data-testid="spend-card"' not in page.text and "$9.40" not in page.text
            assert (await nadia.get("/api/spend", headers={"accept": "application/json"})).status_code == 403


class TestTheApi:
    async def test_the_owner_reads_the_numbers_and_the_alerts(self, rig, owner):
        app, _ = rig
        await _tlphone(owner)
        await _history(app)
        r = await owner.get("/api/spend")
        assert r.status_code == 200
        body = r.json()
        assert body["month"] == f"{month_start(NOW):%B %Y}" and body["total"] == 10.9 and body["total_last"] == 10.0
        tl = next(c for c in body["customers"] if c["name"] == "TLphone")
        assert tl["this_month"] == 9.4 and tl["last_month"] == 10.0 and tl["cycles"] == 1
        assert any(a["kind"] == "dear" and a["cost_usd"] == 9.4 for a in body["anomalies"])

    async def test_the_wall_keeps_it_from_a_stranger(self, rig):
        async with _client(rig[0]) as stranger:
            r = await stranger.get("/api/spend", headers={"accept": "application/json"})
        assert r.status_code == 401


class TestTheChat:
    async def test_a_cycle_that_finishes_dear_is_posted_on_the_po_s_channel(self, rig, owner):
        app, bus = rig
        await _tlphone(owner)
        for i in range(5):
            await _cycle(app, 2.0, LAST_MONTH - timedelta(days=i))
        running = Cycle(id=CycleId("abc123abc123"), project_id=REPO, status=CycleStatus.RUNNING, triggered_by="web", started_at=NOW - timedelta(minutes=20))
        await app.state.cycle_repo.save(running)

        class Chat:
            posts: list = []

            async def post_message(self, channel, text):
                self.posts.append((channel, text))

        chat = Chat()
        chat.posts = []
        app.state.spend_watch.configure_chat(chat, "swarm-bots-logs")
        await bus.publish(CycleCompleted(cycle_id=running.id, project_id=REPO, total_cost_usd=11.0, prs_merged=1, merged_prs=(5,)))
        kinds = [text for _, text in chat.posts]
        assert any("A dear cycle on espace-client: $11.00, against $2.00 usually" in t for t in kinds)
        assert all(channel == "swarm-bots-logs" for channel, _ in chat.posts)
