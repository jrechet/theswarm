"""Phase I presentation tests for Security routes."""

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
    conn = await init_db(str(tmp_path / "security_routes.db"))
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


class TestThreatModelRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/security/threat-model")
        assert r.status_code == 200
        assert "No threat model drafted yet." in r.text

    async def test_upsert(self, client):
        r = await client.post(
            "/projects/demo/security/threat-model",
            data={
                "title": "Baseline",
                "assets": "user data",
                "actors": "attacker",
                "trust_boundaries": "browser ↔ api",
                "stride_notes": "JWT sig",
            },
        )
        assert r.status_code == 200
        assert "Baseline" in r.text
        assert "user data" in r.text
        assert "JWT sig" in r.text


class TestDataInventoryRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/security/data-inventory")
        assert r.status_code == 200
        assert "No data fields inventoried yet." in r.text

    async def test_upsert(self, client):
        r = await client.post(
            "/projects/demo/security/data-inventory",
            data={
                "field_name": "user.email",
                "classification": "pii",
                "storage_notes": "Postgres",
            },
        )
        assert r.status_code == 200
        assert "user.email" in r.text
        assert "pii" in r.text
        assert "sensitive" in r.text

    async def test_unknown_classification_falls_back(self, client):
        r = await client.post(
            "/projects/demo/security/data-inventory",
            data={"field_name": "foo", "classification": "bogus"},
        )
        assert r.status_code == 200
        assert "foo" in r.text
        assert "internal" in r.text


class TestFindingRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/security/findings")
        assert r.status_code == 200
        assert "No findings recorded yet." in r.text

    async def test_open_triage_resolve(self, client):
        r = await client.post(
            "/projects/demo/security/findings",
            data={
                "title": "SSRF in webhook",
                "severity": "high",
                "description": "outbound not validated",
                "cve": "CVE-2024-1",
            },
        )
        assert r.status_code == 200
        assert "SSRF in webhook" in r.text
        assert "high" in r.text
        assert "CVE-2024-1" in r.text

        svc = client._transport.app.state.security_finding_service
        findings = await svc.list("demo")
        assert len(findings) == 1
        fid = findings[0].id

        r = await client.post(
            f"/projects/demo/security/findings/{fid}/triage",
            data={"note": "assigned to sec"},
        )
        assert r.status_code == 200
        assert "triaged" in r.text
        assert "assigned to sec" in r.text

        r = await client.post(
            f"/projects/demo/security/findings/{fid}/resolve",
            data={"note": "patched"},
        )
        assert r.status_code == 200
        assert "resolved" in r.text
        assert "patched" in r.text

    async def test_unknown_severity_falls_back_to_medium(self, client):
        r = await client.post(
            "/projects/demo/security/findings",
            data={"title": "x", "severity": "bogus"},
        )
        assert r.status_code == 200
        assert "medium" in r.text


class TestSBOMRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/security/sbom")
        assert r.status_code == 200
        assert "No SBOM artifacts recorded yet." in r.text

    async def test_record(self, client):
        r = await client.post(
            "/projects/demo/security/sbom",
            data={
                "tool": "syft",
                "package_count": "42",
                "license_summary": "MIT:30;Apache-2.0:12",
                "artifact_path": "artifacts/sbom.json",
            },
        )
        assert r.status_code == 200
        assert "syft" in r.text
        assert "42" in r.text
        assert "MIT:30" in r.text


class TestAuthZRoutes:
    async def test_empty(self, client):
        r = await client.get("/projects/demo/security/authz")
        assert r.status_code == 200
        assert "No AuthZ rules defined yet." in r.text

    async def test_upsert_then_flip(self, client):
        r = await client.post(
            "/projects/demo/security/authz",
            data={
                "actor_role": "admin",
                "resource": "/users",
                "action": "read",
                "effect": "allow",
            },
        )
        assert r.status_code == 200
        assert "admin" in r.text
        assert "/users" in r.text
        assert "allow" in r.text

        r = await client.post(
            "/projects/demo/security/authz",
            data={
                "actor_role": "admin",
                "resource": "/users",
                "action": "read",
                "effect": "deny",
                "notes": "tightened",
            },
        )
        assert r.status_code == 200
        assert "deny" in r.text
        assert "tightened" in r.text

    async def test_unknown_effect_falls_back_to_allow(self, client):
        r = await client.post(
            "/projects/demo/security/authz",
            data={
                "actor_role": "user",
                "resource": "/x",
                "action": "read",
                "effect": "bogus",
            },
        )
        assert r.status_code == 200
        assert "allow" in r.text
