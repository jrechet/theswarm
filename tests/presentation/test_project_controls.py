"""Integration tests for Sprint B — PATCH config, pause/resume, secrets routes."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.secret_vault import SqliteSecretVault
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "ctl.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def repos(db):
    return SQLiteProjectRepository(db), SQLiteCycleRepository(db)


@pytest.fixture()
def vault(db):
    return SqliteSecretVault(db, master_key=Fernet.generate_key())


@pytest.fixture()
def app(repos, vault, db):
    project_repo, cycle_repo = repos
    bus = EventBus()
    return create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        secret_vault=vault, db=db,
    )


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed(repos) -> None:
    project_repo, _ = repos
    await project_repo.save(Project(id="p1", repo=RepoUrl("o/p1")))


class TestPatchConfig:
    async def test_patch_updates_effort_and_caps(self, repos, client):
        await _seed(repos)
        r = await client.patch(
            "/projects/p1/config",
            json={"effort": "high", "daily_cost_cap_usd": 12.5},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["effort"] == "high"
        assert data["daily_cost_cap_usd"] == 12.5

    async def test_patch_rejects_invalid_effort(self, repos, client):
        await _seed(repos)
        r = await client.patch("/projects/p1/config", json={"effort": "extreme"})
        assert r.status_code == 422

    async def test_patch_missing_project_404(self, client):
        r = await client.patch("/projects/ghost/config", json={"effort": "low"})
        assert r.status_code == 404

    async def test_patch_form_with_models(self, repos, client):
        await _seed(repos)
        r = await client.patch(
            "/projects/p1/config",
            data={"models": "dev=opus,po=sonnet"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["models"]["dev"] == "opus"


class TestPauseResume:
    async def test_pause_then_resume(self, repos, client):
        await _seed(repos)
        r = await client.post("/projects/p1/pause")
        assert r.status_code == 200
        assert r.json()["paused"] is True

        r2 = await client.post("/projects/p1/resume")
        assert r2.status_code == 200
        assert r2.json()["paused"] is False

    async def test_pause_writes_audit_row(self, repos, client, db):
        await _seed(repos)
        await client.post("/projects/p1/pause", headers={"x-actor": "jre"})
        cursor = await db.execute(
            "SELECT action, actor FROM project_audit WHERE project_id = ?",
            ("p1",),
        )
        rows = await cursor.fetchall()
        actions = [r["action"] for r in rows]
        actors = [r["actor"] for r in rows]
        assert "pause" in actions
        assert "jre" in actors

    async def test_pause_missing_project_404(self, client):
        r = await client.post("/projects/ghost/pause")
        assert r.status_code == 404


class TestSecrets:
    async def test_set_list_delete(self, repos, client, vault):
        await _seed(repos)
        r = await client.post(
            "/projects/p1/secrets",
            data={"key_name": "API_KEY", "value": "s3cret"},
        )
        assert r.status_code == 200, r.text

        # The secret value must not appear in any API response
        keys = await vault.list_keys("p1")
        assert "API_KEY" in keys
        assert "s3cret" not in r.text

        # Plaintext round-trips via the vault (not the HTTP layer)
        assert await vault.get("p1", "API_KEY") == "s3cret"

        r2 = await client.delete("/projects/p1/secrets/API_KEY")
        assert r2.status_code == 204
        assert await vault.get("p1", "API_KEY") is None

    async def test_set_rejects_missing_value(self, repos, client):
        await _seed(repos)
        r = await client.post(
            "/projects/p1/secrets",
            data={"key_name": "", "value": ""},
        )
        # Empty values are rejected by FastAPI Form required validation (422)
        assert r.status_code in (422,)

    async def test_detail_page_lists_secret_keys_only(self, repos, client, vault):
        await _seed(repos)
        await vault.set("p1", "DB_URL", "postgres://very-secret")
        r = await client.get("/projects/p1")
        assert r.status_code == 200
        assert "DB_URL" in r.text
        # Plaintext must never appear in the HTML
        assert "very-secret" not in r.text
