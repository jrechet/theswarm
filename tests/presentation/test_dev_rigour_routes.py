"""Phase E presentation tests for Dev-rigour routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.dev_rigour.value_objects import (
    FindingSeverity,
    PreflightDecision,
    ThoughtKind,
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
    conn = await init_db(str(tmp_path / "dev_routes.db"))
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


class TestDevThoughtRoutes:
    async def test_empty_fragment(self, client):
        r = await client.get("/projects/demo/dev/thoughts")
        assert r.status_code == 200
        assert "No dev thoughts" in r.text

    async def test_log_thought(self, client):
        r = await client.post(
            "/projects/demo/dev/thoughts",
            data={
                "content": "grepped auth module for role checks",
                "kind": "explore",
                "task_id": "T-42",
            },
        )
        assert r.status_code == 200
        assert "grepped auth module" in r.text
        assert "explore" in r.text

    async def test_blank_content_is_ignored(self, client):
        r = await client.post(
            "/projects/demo/dev/thoughts",
            data={"content": "   ", "kind": "note"},
        )
        assert r.status_code == 200
        assert "No dev thoughts" in r.text


class TestTddRoutes:
    async def test_empty_tdd(self, client):
        r = await client.get("/projects/demo/dev/tdd")
        assert r.status_code == 200
        assert "No TDD artifacts" in r.text

    async def test_red_then_green(self, client):
        r1 = await client.post(
            "/projects/demo/dev/tdd/red",
            data={
                "task_id": "T-1",
                "test_files": "tests/test_x.py",
                "commit": "abcdef1234",
            },
        )
        assert r1.status_code == 200
        assert "T-1" in r1.text
        assert "red" in r1.text

        r2 = await client.post(
            "/projects/demo/dev/tdd/T-1/green",
            data={"commit": "beefcafe0000"},
        )
        assert r2.status_code == 200
        assert "green" in r2.text


class TestPreflightRoutes:
    async def test_empty_preflight(self, client):
        r = await client.get("/projects/demo/dev/preflight")
        assert r.status_code == 200
        assert "No preflight checks" in r.text
        assert "≥ 20 lines" in r.text  # shows default threshold

    async def test_below_threshold_not_logged(self, client):
        r = await client.post(
            "/projects/demo/dev/preflight",
            data={
                "deletion_lines": "5",
                "decision": "proceed",
            },
        )
        assert r.status_code == 200
        assert "No preflight checks" in r.text

    async def test_log_preflight(self, client):
        r = await client.post(
            "/projects/demo/dev/preflight",
            data={
                "deletion_lines": "42",
                "decision": "bail",
                "reason": "unclear callers",
                "files_touched": "src/legacy.py",
                "callers_checked": "app.py",
            },
        )
        assert r.status_code == 200
        assert "42" in r.text
        assert "unclear callers" in r.text


class TestSelfReviewRoute:
    async def test_empty_self_reviews(self, client):
        r = await client.get("/projects/demo/dev/self-reviews")
        assert r.status_code == 200
        assert "No self-reviews" in r.text

    async def test_lists_recorded_review(self, client, app):
        svc = app.state.self_review_service
        f = svc.make_finding(
            severity=FindingSeverity.HIGH,
            category="duplication",
            message="dup of helpers.foo",
        )
        await svc.record(
            project_id="demo",
            pr_url="http://pr/1",
            findings=(f,),
            summary="one HIGH",
        )
        r = await client.get("/projects/demo/dev/self-reviews")
        assert r.status_code == 200
        assert "high" in r.text
        assert "duplication" in r.text
        assert "one HIGH" in r.text


class TestCoverageRoute:
    async def test_empty_coverage(self, client):
        r = await client.get("/projects/demo/dev/coverage")
        assert r.status_code == 200
        assert "No coverage deltas" in r.text

    async def test_coverage_after_record(self, client, app):
        svc = app.state.coverage_delta_service
        await svc.record(
            project_id="demo",
            pr_url="http://pr/2",
            total_before_pct=78.0,
            total_after_pct=83.5,
            changed_lines_pct=90.0,
            changed_lines=40,
            missed_lines=4,
        )
        r = await client.get("/projects/demo/dev/coverage")
        assert r.status_code == 200
        assert "90.0%" in r.text
        assert "83.5%" in r.text


class TestThoughtKindFallback:
    async def test_unknown_kind_falls_back_to_note(self, client):
        r = await client.post(
            "/projects/demo/dev/thoughts",
            data={"content": "hello", "kind": "bogus"},
        )
        assert r.status_code == 200
        assert "hello" in r.text
