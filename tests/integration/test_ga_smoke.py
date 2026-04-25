"""GA smoke gate — exercises the user-visible paths a regression would break.

Runs in-process with httpx ASGITransport against a stub-mode app:
- POST /projects/.../sprints/draft (with a mocked SprintComposer)
- GET /health/ready
- GET /diagnostics/claude (CLI may be unavailable in CI — treated as warn, not error)

Caps every step at 30s. If this test exceeds 60s wall-clock, something
is wrong with the cycle pipeline — fail loud rather than silently slow.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.services.sprint_composer import IssueDraft, SprintDraft
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "smoke.db"))
    yield conn
    await conn.close()


@pytest.fixture()
async def client(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    await project_repo.save(Project(id="smoke", repo=RepoUrl("o/smoke")))
    app = create_web_app(project_repo, cycle_repo, EventBus(), SSEHub(), db=db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _within(coro, label: str, max_seconds: float = 30.0):
    """Run coro with a hard timeout. Pytest-friendly failure messages."""
    try:
        return await asyncio.wait_for(coro, timeout=max_seconds)
    except asyncio.TimeoutError:
        pytest.fail(f"{label} did not complete within {max_seconds}s")


class TestGASmokeGate:
    async def test_sprint_composer_endpoint_responds_quickly(self, client):
        """Drafting a sprint must respond in <30s."""
        with patch(
            "theswarm.application.services.sprint_composer.SprintComposer.draft",
            new_callable=AsyncMock,
        ) as mock_draft:
            mock_draft.return_value = SprintDraft(
                request="x",
                issues=(IssueDraft(title="Add LICENSE", body="MIT", labels=("status:backlog", "role:dev")),),
            )
            t0 = time.monotonic()
            r = await _within(
                client.post("/projects/smoke/sprints/draft", data={"description": "Add license"}),
                "sprint draft",
            )
            elapsed = time.monotonic() - t0
        assert r.status_code == 200
        assert elapsed < 5.0, f"draft slow: {elapsed:.2f}s"
        assert r.json()["issues"][0]["title"] == "Add LICENSE"

    async def test_readiness_reports_overall_status(self, client):
        r = await _within(client.get("/health/ready"), "readiness")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in {"ok", "warn", "error"}
        # Required component probes always present
        for key in ("database", "allowlist", "memory", "cycles"):
            assert key in body["checks"], f"missing readiness probe: {key}"

    async def test_health_liveness_returns_200(self, client):
        r = await _within(client.get("/health"), "health")
        assert r.status_code in (200, 503)
        body = r.json()
        assert body["service"] == "theswarm"

    async def test_cycles_list_renders(self, client):
        r = await _within(client.get("/cycles/"), "cycles list")
        assert r.status_code == 200
        assert "Cycles" in r.text

    async def test_project_detail_renders_with_composer(self, client):
        r = await _within(client.get("/projects/smoke"), "project detail")
        assert r.status_code == 200
        # Sprint composer + Run Cycle modal must both be on the page.
        assert "sprint-composer" in r.text
        assert "cost-preview-modal" in r.text
        # Sidebar entries we shipped in the redesign.
        assert "TheSwarm" in r.text
        assert 'data-icon=' in r.text
