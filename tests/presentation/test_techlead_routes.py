"""Phase D presentation tests for TechLead intelligence routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.techlead.value_objects import (
    DebtSeverity,
    DepSeverity,
    ReviewDecision,
    ReviewOutcome,
)
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "tl_routes.db"))
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


class TestDepsRoutes:
    async def test_empty_deps_fragment(self, client):
        r = await client.get("/projects/demo/deps")
        assert r.status_code == 200
        assert "No findings" in r.text
        assert "Scan now" in r.text

    async def test_scan_with_registered_scanner(self, client, app):
        radar = app.state.dependency_radar

        async def fake_scanner(pid: str):
            return [{
                "package": "requests",
                "advisory_id": "CVE-2024-1",
                "severity": DepSeverity.HIGH.value,
                "summary": "SSRF bug",
            }]

        radar.register_scanner("fake", fake_scanner)
        r = await client.post("/projects/demo/deps/scan")
        assert r.status_code == 200
        assert "requests" in r.text
        assert "CVE-2024-1" in r.text


class TestADRRoutes:
    async def test_empty_adrs_fragment(self, client):
        r = await client.get("/projects/demo/adrs")
        assert r.status_code == 200
        assert "No ADRs" in r.text

    async def test_create_adr_and_list(self, client):
        r = await client.post(
            "/projects/demo/adrs",
            data={
                "title": "Adopt Event Bus",
                "context": "decoupling",
                "decision": "Use in-process bus",
                "consequences": "testability",
            },
        )
        assert r.status_code == 200
        assert "Adopt Event Bus" in r.text

    async def test_accept_adr(self, client, app):
        await app.state.adr_service.propose(project_id="demo", title="t")
        adrs = await app.state.adr_service.list("demo")
        r = await client.post(f"/projects/demo/adrs/{adrs[0].id}/accept")
        assert r.status_code == 200
        refreshed = await app.state.adr_service.list("demo")
        assert refreshed[0].status.value == "accepted"

    async def test_adr_detail(self, client, app):
        adr = await app.state.adr_service.propose(
            project_id="demo", title="T1", context="ctx",
        )
        r = await client.get(f"/projects/demo/adrs/{adr.id}")
        assert r.status_code == 200
        assert "T1" in r.text
        assert "ctx" in r.text


class TestDebtRoutes:
    async def test_empty_debt_fragment(self, client):
        r = await client.get("/projects/demo/debt")
        assert r.status_code == 200
        assert "No debt" in r.text

    async def test_add_debt(self, client):
        r = await client.post(
            "/projects/demo/debt",
            data={
                "title": "Legacy handler",
                "severity": DebtSeverity.HIGH.value,
                "blast_radius": "auth",
                "description": "needs refactor",
            },
        )
        assert r.status_code == 200
        assert "Legacy handler" in r.text
        assert "high" in r.text

    async def test_resolve_debt(self, client, app):
        item = await app.state.debt_service.add(project_id="demo", title="t")
        r = await client.post(f"/projects/demo/debt/{item.id}/resolve")
        assert r.status_code == 200
        assert "t" not in r.text.split("tl-debt-list")[-1] or "No debt" in r.text


class TestCalibrationRoute:
    async def test_empty_calibration(self, client):
        r = await client.get("/projects/demo/reviews/calibration")
        assert r.status_code == 200
        assert "No reviews" in r.text

    async def test_calibration_after_recording(self, client, app):
        svc = app.state.review_calibration_service
        v = await svc.record(
            project_id="demo",
            pr_url="http://pr/1",
            reviewer_codename="Marcus",
            decision=ReviewDecision.APPROVE,
        )
        await svc.set_outcome(v.id, ReviewOutcome.REVERTED)
        r = await client.get("/projects/demo/reviews/calibration")
        assert r.status_code == 200
        assert "Reviews on record" in r.text
        assert "100.0%" in r.text  # FN rate = 100% since 1 approve reverted


class TestCriticalPathRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/critical-paths")
        assert r.status_code == 200
        assert "No critical paths" in r.text

    async def test_add_and_remove(self, client, app):
        r = await client.post(
            "/projects/demo/critical-paths",
            data={"pattern": "auth/*", "reason": "PII"},
        )
        assert r.status_code == 200
        assert "auth/*" in r.text
        assert "PII" in r.text
        paths = await app.state.second_opinion_service.list_critical_paths("demo")
        r2 = await client.post(
            f"/projects/demo/critical-paths/{paths[0].id}/delete",
        )
        assert r2.status_code == 200
        assert "No critical paths" in r2.text
