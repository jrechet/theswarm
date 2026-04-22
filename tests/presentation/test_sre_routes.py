"""Phase I presentation tests for SRE routes."""

from __future__ import annotations

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


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "sre_routes.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def app(db):
    return create_web_app(
        SQLiteProjectRepository(db), SQLiteCycleRepository(db),
        EventBus(), SSEHub(), db=db,
    )


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestDeploymentRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/sre/deployments")
        assert r.status_code == 200
        assert "No deployments recorded yet." in r.text

    async def test_start_then_succeed(self, client):
        r = await client.post(
            "/projects/demo/sre/deployments",
            data={
                "version": "1.2.3",
                "environment": "production",
                "triggered_by": "sre-bot",
                "notes": "canary first",
            },
        )
        assert r.status_code == 200
        assert "1.2.3" in r.text
        assert "in_progress" in r.text
        assert "canary first" in r.text

        svc = client._transport.app.state.deployment_service
        deploys = await svc.list("demo")
        assert len(deploys) == 1
        did = deploys[0].id

        r = await client.post(
            f"/projects/demo/sre/deployments/{did}/succeed",
            data={"notes": "all green"},
        )
        assert r.status_code == 200
        assert "success" in r.text
        assert "all green" in r.text

    async def test_fail_and_rollback(self, client):
        r = await client.post(
            "/projects/demo/sre/deployments",
            data={"version": "1.2.4"},
        )
        assert r.status_code == 200

        svc = client._transport.app.state.deployment_service
        deploys = await svc.list("demo")
        did = deploys[0].id

        r = await client.post(
            f"/projects/demo/sre/deployments/{did}/fail",
            data={"notes": "migration died"},
        )
        assert r.status_code == 200
        assert "failed" in r.text
        assert "migration died" in r.text

        r = await client.post(
            "/projects/demo/sre/deployments",
            data={"version": "1.2.5"},
        )
        deploys = await svc.list("demo")
        did2 = [d.id for d in deploys if d.version == "1.2.5"][0]

        r = await client.post(
            f"/projects/demo/sre/deployments/{did2}/rollback",
            data={"notes": "auto-revert"},
        )
        assert r.status_code == 200
        assert "rolled_back" in r.text


class TestIncidentRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/sre/incidents")
        assert r.status_code == 200
        assert "No incidents recorded yet." in r.text

    async def test_full_lifecycle(self, client):
        r = await client.post(
            "/projects/demo/sre/incidents",
            data={
                "title": "5xx spike",
                "severity": "sev1",
                "summary": "error rate 10%",
            },
        )
        assert r.status_code == 200
        assert "5xx spike" in r.text
        assert "sev1" in r.text

        svc = client._transport.app.state.incident_service
        incidents = await svc.list("demo")
        iid = incidents[0].id

        # timeline append (available at any time)
        r = await client.post(
            f"/projects/demo/sre/incidents/{iid}/timeline",
            data={"note": "rolled back image"},
        )
        assert r.status_code == 200
        assert "rolled back image" in r.text

        # triage
        r = await client.post(
            f"/projects/demo/sre/incidents/{iid}/triage",
            data={"note": "oncall engaged"},
        )
        assert r.status_code == 200
        assert "triaged" in r.text

        # mitigate
        r = await client.post(
            f"/projects/demo/sre/incidents/{iid}/mitigate",
            data={"note": "error rate < 1%"},
        )
        assert r.status_code == 200
        assert "mitigated" in r.text

        # resolve
        r = await client.post(
            f"/projects/demo/sre/incidents/{iid}/resolve",
            data={"note": "clean 30min"},
        )
        assert r.status_code == 200
        assert "resolved" in r.text

        # postmortem
        r = await client.post(
            f"/projects/demo/sre/incidents/{iid}/postmortem",
            data={"postmortem": "Root cause: unbounded query"},
        )
        assert r.status_code == 200
        assert "postmortem_done" in r.text
        assert "unbounded query" in r.text

    async def test_unknown_severity_falls_back(self, client):
        r = await client.post(
            "/projects/demo/sre/incidents",
            data={"title": "small", "severity": "bogus"},
        )
        assert r.status_code == 200
        assert "sev3" in r.text


class TestCostRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/sre/cost")
        assert r.status_code == 200
        assert "No cost samples recorded yet." in r.text
        assert "$0.00" in r.text

    async def test_record_and_rollup(self, client):
        r = await client.post(
            "/projects/demo/sre/cost",
            data={
                "source": "ai",
                "amount_usd": "4.20",
                "window": "daily",
                "description": "claude tokens",
            },
        )
        assert r.status_code == 200
        assert "4.20" in r.text
        assert "ai" in r.text

        r = await client.post(
            "/projects/demo/sre/cost",
            data={
                "source": "infra",
                "amount_usd": "12.50",
                "window": "daily",
            },
        )
        assert r.status_code == 200
        assert "12.50" in r.text
        assert "infra" in r.text
        # total = 16.70
        assert "16.70" in r.text

    async def test_unknown_source_falls_back_to_other(self, client):
        r = await client.post(
            "/projects/demo/sre/cost",
            data={"source": "bogus", "amount_usd": "1.00"},
        )
        assert r.status_code == 200
        assert "other" in r.text
