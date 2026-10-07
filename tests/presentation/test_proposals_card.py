"""DevOps D3 on the product: the watch raises proposals from each report, the
owner sees them on the home with one click each, approve runs the command on
the host and the answer is on the card, refuse keeps the no; a member never
sees or decides one.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.agents.devops import Finding, OpsReport, read_host, run_host
from theswarm.application.events.bus import EventBus
from theswarm.application.services.ops_watch import OpsWatch
from theswarm.application.services.proposals import ProposalService
from theswarm.infrastructure.persistence.ops_repo import SQLiteProposalRepository
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
STACK = {
    "hosts": [{"name": "jrec.fr", "ssh": "debian@jrec.fr", "port": 5422, "ci_slot_dir": "/srv/gh-runner-work/ci-slots"}],
    "ci": [{"provider": "github-actions", "repo": "jrechet/theswarm", "runner_service": "github_runner_runner_theswarm"}],
}
STALE = Finding("ci_slot", "CI slot", "bad", "stale: slot1 held by runner-areza (jrechet/areza) for 240 min — past the 180 min rule on jrec.fr")
FINE = Finding("claude", "Claude", "ok", "credentials and window fine")


def _report(*findings) -> OpsReport:
    return OpsReport(tuple(findings), read_at=NOW, stack="jrec.fr · github-actions")


@pytest.fixture(autouse=True)
def _wall(monkeypatch):
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("SWARM_ACCESS_KEY", KEY)


@pytest.fixture()
async def rig(tmp_path):
    """The app with a stack, a proposals service on a recording runner, and a watch that raises."""
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(), db=conn)
    ran: list[tuple[str, str]] = []

    async def runner(host, command):
        ran.append((host["name"], command))
        return "slot1 removed"

    service = ProposalService(SQLiteProposalRepository(conn), STACK, runner)
    app.state.proposal_service = service
    reports = [_report(STALE, FINE)]

    async def gather():
        return reports[-1]

    async def raise_proposals(report):
        await service.raise_from(report.findings, report.facts)

    app.state.ops_watch = OpsWatch(gather, clock=lambda: NOW, on_report=raise_proposals)
    yield app, service, ran, reports
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


class TestTheProposalOnTheHome:
    async def test_the_watch_raises_and_the_owner_approves_with_one_click(self, rig, owner):
        app, service, ran, _ = rig
        r = await _home(owner)
        assert 'data-testid="proposal"' not in r.text  # nothing read yet
        await app.state.ops_watch.refresh()
        [p] = await service.open()
        assert p.kind == "clear_slot"
        r = await _home(owner)
        assert f'data-testid="proposal" data-proposal="{p.id}" data-kind="clear_slot"' in r.text
        assert "DevOps proposes: Clear the CI slot slot1 on jrec.fr" in r.text
        assert "sudo rm -rf /srv/gh-runner-work/ci-slots/slot1" in r.text
        assert f'data-testid="approve-{p.id}"' in r.text and f'data-testid="refuse-{p.id}"' in r.text
        r = await owner.post(f"/ops/proposals/{p.id}/approve", headers=HTML)
        assert r.status_code == 303 and r.headers["location"].endswith("/#ops")
        assert ran == [("jrec.fr", "sudo rm -rf /srv/gh-runner-work/ci-slots/slot1")]
        r = await _home(owner)
        assert 'data-testid="proposal"' not in r.text
        assert 'data-testid="proposal-decided" data-status="run"' in r.text and "slot1 removed" in r.text and "by owner" in r.text
        await app.state.ops_watch.refresh()  # the slot is stale again on the next read: a new proposal, the old one decided
        assert len(await service.open()) == 1 and (await service.open())[0].id != p.id

    async def test_refuse_keeps_the_no_and_runs_nothing(self, rig, owner):
        app, service, ran, _ = rig
        await app.state.ops_watch.refresh()
        [p] = await service.open()
        r = await owner.post(f"/ops/proposals/{p.id}/refuse", headers=HTML)
        assert r.status_code == 303 and ran == []
        r = await _home(owner)
        assert 'data-testid="proposal-decided" data-status="refused"' in r.text
        r = await owner.get("/api/devops/proposals")
        assert r.status_code == 200 and r.json()["open"] == [] and r.json()["recent"][0]["status"] == "refused"
        r = await owner.post(f"/ops/proposals/{p.id}/approve", headers=HTML)  # a refusal stands
        assert r.status_code == 303 and ran == []
        r = await owner.post(f"/ops/proposals/{p.id}/maybe", headers=HTML)
        assert r.status_code == 303 and ran == []

    async def test_a_member_never_sees_nor_decides_one(self, rig, owner):
        app, service, ran, _ = rig
        await app.state.ops_watch.refresh()
        [p] = await service.open()
        r = await owner.post("/settings/customers", data={"name": "TLphone"})
        assert r.status_code == 303
        r = await owner.post("/settings/customers/tlphone/members", data={"email": "nadia@tlphone.fr", "display_name": "Nadia"})
        link = re.search(r'value="(http://test/invite/[^"]+)"', r.text).group(1).replace("http://test", "")
        async with _client(app) as nadia:
            r = await nadia.get(link)
            assert r.status_code == 303 and SESSION_COOKIE in nadia.cookies
            r = await nadia.post(f"/ops/proposals/{p.id}/approve", headers=HTML)
            assert r.status_code == 403 and ran == []
            r = await nadia.get("/api/devops/proposals", headers={"accept": "application/json"})
            assert r.status_code == 403
            r = await nadia.get("/c/tlphone", headers=HTML)
            assert r.status_code == 200 and "DevOps proposes" not in r.text

    async def test_without_a_stack_the_home_and_the_api_stay_quiet(self, tmp_path):
        conn = await init_db(str(tmp_path / "bare.db"))
        app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(), db=conn)
        try:
            assert app.state.proposal_service is None
            async with _client(app) as client:
                await client.post("/login", data={"access_key": KEY})
                r = await client.get("/api/devops/proposals")
                assert r.status_code == 200 and r.json() == {"open": [], "recent": []}
                r = await _home(client)
                assert r.status_code == 200 and "DevOps proposes" not in r.text
        finally:
            await conn.close()


class TestAHostThatIsThisBox:
    async def test_a_local_host_runs_the_same_script_in_a_shell(self, tmp_path):
        slot = tmp_path / "slots" / "slot1"
        slot.mkdir(parents=True)
        (slot / "owner").write_text("runner-x\njrechet/x\n2026-10-07T10:00:00Z\nabc\ncontainer\n")
        assert (await run_host({"name": "here", "local": True}, "echo hello")).strip() == "hello"
        read = await read_host({"name": "here", "local": True, "ci_slot_dir": str(tmp_path / "slots"), "disk_paths": [str(tmp_path)]})
        assert read["slots"][0][0].endswith("slot1/owner") and "jrechet/x" in read["slots"][0][1]
        assert read["disks"]  # the load needs /proc/loadavg, which a Mac has not
        with pytest.raises(RuntimeError, match="no such|not found|exit"):
            await run_host({"name": "here", "local": True}, "exit 3")
