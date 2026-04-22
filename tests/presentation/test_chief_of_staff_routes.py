"""Phase K presentation tests for Chief of Staff routes."""

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
    conn = await init_db(str(tmp_path / "cos_routes.db"))
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


class TestRoutingRoutes:
    async def test_empty(self, client):
        r = await client.get("/chief-of-staff/routing")
        assert r.status_code == 200
        assert "No routing rules yet." in r.text

    async def test_upsert_creates_rule(self, client):
        r = await client.post(
            "/chief-of-staff/routing",
            data={
                "pattern": "security",
                "target_role": "security_agent",
                "target_codename": "Ada",
                "priority": "5",
                "status": "active",
            },
        )
        assert r.status_code == 200
        assert "security" in r.text
        assert "security_agent" in r.text
        assert "p5" in r.text
        assert "active" in r.text

    async def test_upsert_regex_pattern_roundtrip(self, client):
        r = await client.post(
            "/chief-of-staff/routing",
            data={
                "pattern": "re:deploy.*prod",
                "target_role": "sre",
            },
        )
        assert r.status_code == 200
        assert "re:deploy.*prod" in r.text
        assert "sre" in r.text

    async def test_unknown_status_falls_back_to_active(self, client):
        r = await client.post(
            "/chief-of-staff/routing",
            data={
                "pattern": "bug",
                "target_role": "qa",
                "status": "bogus",
            },
        )
        assert r.status_code == 200
        assert "bug" in r.text
        assert "active" in r.text

    async def test_disable_happy_path(self, client):
        await client.post(
            "/chief-of-staff/routing",
            data={"pattern": "bug", "target_role": "qa"},
        )
        r = await client.post(
            "/chief-of-staff/routing/disable",
            data={"pattern": "bug"},
        )
        assert r.status_code == 200
        assert "disabled" in r.text

    async def test_disable_missing_returns_404(self, client):
        r = await client.post(
            "/chief-of-staff/routing/disable",
            data={"pattern": "missing"},
        )
        assert r.status_code == 404


class TestBudgetRoutes:
    async def test_empty(self, client):
        r = await client.get("/chief-of-staff/budgets")
        assert r.status_code == 200
        assert "No budget policies configured." in r.text

    async def test_upsert_portfolio(self, client):
        r = await client.post(
            "/chief-of-staff/budgets",
            data={
                "project_id": "",
                "daily_tokens_limit": "100000",
                "daily_cost_usd_limit": "25.5",
                "state": "active",
                "note": "global cap",
            },
        )
        assert r.status_code == 200
        assert "portfolio" in r.text
        assert "100000" in r.text
        assert "25.50" in r.text

    async def test_upsert_project_scoped(self, client):
        r = await client.post(
            "/chief-of-staff/budgets",
            data={
                "project_id": "proj-42",
                "daily_tokens_limit": "5000",
            },
        )
        assert r.status_code == 200
        assert "proj-42" in r.text
        assert "5000" in r.text

    async def test_set_state_happy_path(self, client):
        await client.post(
            "/chief-of-staff/budgets",
            data={"project_id": "p", "daily_tokens_limit": "1000"},
        )
        r = await client.post(
            "/chief-of-staff/budgets/state",
            data={"project_id": "p", "state": "exceeded"},
        )
        assert r.status_code == 200
        assert "exceeded" in r.text
        assert "blocks cycles" in r.text

    async def test_set_state_missing_returns_404(self, client):
        r = await client.post(
            "/chief-of-staff/budgets/state",
            data={"project_id": "nope", "state": "paused"},
        )
        assert r.status_code == 404


class TestOnboardingRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/p1/chief-of-staff/onboarding")
        assert r.status_code == 200
        assert "No onboarding steps yet." in r.text
        assert "0/0 done" in r.text

    async def test_seed_creates_default_checklist(self, client):
        r = await client.post(
            "/projects/p1/chief-of-staff/onboarding/seed",
        )
        assert r.status_code == 200
        assert "0/5 done" in r.text
        assert "create_roster" in r.text
        assert "assign_codenames" in r.text
        assert "seed_memory" in r.text
        assert "confirm_config" in r.text
        assert "first_cycle" in r.text

    async def test_mark_status_happy_path(self, client):
        await client.post("/projects/p1/chief-of-staff/onboarding/seed")
        r = await client.post(
            "/projects/p1/chief-of-staff/onboarding/create_roster/status",
            data={"status": "complete", "note": "done"},
        )
        assert r.status_code == 200
        assert "1/5 done" in r.text
        assert "complete" in r.text

    async def test_mark_status_bad_enum_returns_400(self, client):
        await client.post("/projects/p1/chief-of-staff/onboarding/seed")
        r = await client.post(
            "/projects/p1/chief-of-staff/onboarding/create_roster/status",
            data={"status": "bogus"},
        )
        assert r.status_code == 400

    async def test_mark_status_missing_step_returns_404(self, client):
        r = await client.post(
            "/projects/p1/chief-of-staff/onboarding/nope/status",
            data={"status": "complete"},
        )
        assert r.status_code == 404


class TestArchiveRoutes:
    async def test_empty(self, client):
        r = await client.get("/chief-of-staff/archive")
        assert r.status_code == 200
        assert "No archived projects." in r.text

    async def test_archive_project(self, client):
        r = await client.post(
            "/chief-of-staff/archive",
            data={
                "project_id": "retired-proj",
                "reason": "shipped",
                "memory_frozen": "1",
                "export_path": "~/.swarm-data/archive/retired-proj.json",
                "note": "launched successfully",
            },
        )
        assert r.status_code == 200
        assert "retired-proj" in r.text
        assert "shipped" in r.text
        assert "memory frozen" in r.text
        assert "launched successfully" in r.text

    async def test_archive_unknown_reason_falls_back(self, client):
        r = await client.post(
            "/chief-of-staff/archive",
            data={"project_id": "x", "reason": "bogus"},
        )
        assert r.status_code == 200
        assert "other" in r.text
