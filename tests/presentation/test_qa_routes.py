"""Phase F presentation tests for QA-enrichment routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.qa.value_objects import GateName, GateStatus, TestArchetype
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "qa_routes.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def app(db):
    bus = EventBus()
    hub = SSEHub()
    return create_web_app(
        SQLiteProjectRepository(db),
        SQLiteCycleRepository(db),
        bus,
        hub,
        db=db,
    )


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestArchetypeMixRoutes:
    async def test_empty_plans(self, client):
        r = await client.get("/projects/demo/qa/plans")
        assert r.status_code == 200
        assert "No test plans" in r.text

    async def test_set_and_mark_produced(self, client):
        r = await client.post(
            "/projects/demo/qa/plans",
            data={
                "task_id": "T-1",
                "required": "unit,e2e,a11y",
                "notes": "new login flow",
            },
        )
        assert r.status_code == 200
        assert "T-1" in r.text
        assert "a11y" in r.text

        r2 = await client.post(
            "/projects/demo/qa/plans/T-1/produced",
            data={"archetype": "unit"},
        )
        assert r2.status_code == 200
        assert "unit ✓" in r2.text

    async def test_mark_produced_unknown_archetype_rejected(self, client):
        # set up required first
        await client.post(
            "/projects/demo/qa/plans",
            data={"task_id": "T-9", "required": "unit"},
        )
        r = await client.post(
            "/projects/demo/qa/plans/T-9/produced",
            data={"archetype": "bogus"},
        )
        assert r.status_code == 400


class TestFlakeRoutes:
    async def test_empty_flakes(self, client):
        r = await client.get("/projects/demo/qa/flakes")
        assert r.status_code == 200
        assert "No flake data" in r.text

    async def test_record_pass(self, client):
        r = await client.post(
            "/projects/demo/qa/flakes",
            data={"test_id": "tests/x::y", "failed": "false"},
        )
        assert r.status_code == 200
        assert "tests/x::y" in r.text
        assert "0%" in r.text

    async def test_record_fail_with_reason(self, client):
        r = await client.post(
            "/projects/demo/qa/flakes",
            data={
                "test_id": "tests/x::y",
                "failed": "true",
                "failure_reason": "timeout",
            },
        )
        assert r.status_code == 200
        assert "timeout" in r.text


class TestQuarantineRoutes:
    async def test_empty_quarantine(self, client):
        r = await client.get("/projects/demo/qa/quarantine")
        assert r.status_code == 200
        assert "No tests currently quarantined" in r.text

    async def test_quarantine_and_release(self, client):
        r = await client.post(
            "/projects/demo/qa/quarantine",
            data={"test_id": "tests/x::y", "reason": "flaky"},
        )
        assert r.status_code == 200
        assert "tests/x::y" in r.text
        assert "flaky" in r.text

        # Extract entry id via service
        svc = client._transport.app.state.quarantine_service  # type: ignore[attr-defined]
        active = await svc.list_active("demo")
        assert len(active) == 1
        entry_id = active[0].id

        r2 = await client.post(
            f"/projects/demo/qa/quarantine/{entry_id}/release",
            data={"reason": "fixed upstream"},
        )
        assert r2.status_code == 200
        assert "fixed upstream" in r2.text
        assert "No tests currently quarantined" in r2.text


class TestGateRoutes:
    async def test_empty_gates(self, client):
        r = await client.get("/projects/demo/qa/gates")
        assert r.status_code == 200
        # Every gate should appear as "never run" initially
        assert "never run" in r.text
        for gate in GateName:
            assert gate.value in r.text

    async def test_record_gate(self, client):
        r = await client.post(
            "/projects/demo/qa/gates",
            data={
                "gate": "axe",
                "status": "fail",
                "summary": "3 violations",
                "finding_count": "3",
            },
        )
        assert r.status_code == 200
        assert "3 violations" in r.text

    async def test_unknown_gate_rejected(self, client):
        r = await client.post(
            "/projects/demo/qa/gates",
            data={"gate": "bogus", "status": "pass"},
        )
        assert r.status_code == 400

    async def test_unknown_status_falls_back(self, client):
        # should not 400 — unknown status falls back to UNKNOWN
        r = await client.post(
            "/projects/demo/qa/gates",
            data={"gate": "axe", "status": "bogus"},
        )
        assert r.status_code == 200


class TestOutcomeRoute:
    async def test_empty_outcomes(self, client):
        r = await client.get("/projects/demo/qa/outcomes")
        assert r.status_code == 200
        assert "No outcome cards" in r.text

    async def test_outcome_after_create(self, client, app):
        svc = app.state.outcome_card_service
        a1 = svc.make_acceptance(text="loads", passed=True)
        a2 = svc.make_acceptance(text="locked", passed=False)
        await svc.create(
            project_id="demo",
            title="Login flow",
            acceptance=(a1, a2),
            metric_name="TTI",
            metric_before="3s",
            metric_after="1.5s",
        )
        r = await client.get("/projects/demo/qa/outcomes")
        assert r.status_code == 200
        assert "Login flow" in r.text
        assert "loads" in r.text
        assert "locked" in r.text
        assert "TTI" in r.text
