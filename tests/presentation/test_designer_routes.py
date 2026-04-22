"""Phase H presentation tests for Designer routes."""

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
    conn = await init_db(str(tmp_path / "designer_routes.db"))
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


class TestDesignTokensRoutes:
    async def test_empty_tokens(self, client):
        r = await client.get("/projects/demo/design/tokens")
        assert r.status_code == 200
        assert "No design tokens defined yet." in r.text

    async def test_set_and_list(self, client):
        r = await client.post(
            "/projects/demo/design/tokens",
            data={
                "name": "--color-accent",
                "kind": "color",
                "value": "oklch(68% 0.21 250)",
                "notes": "brand accent",
            },
        )
        assert r.status_code == 200
        assert "--color-accent" in r.text
        assert "oklch(68% 0.21 250)" in r.text

    async def test_unknown_kind_falls_back_to_other(self, client):
        r = await client.post(
            "/projects/demo/design/tokens",
            data={"name": "--foo", "kind": "bogus", "value": "1px"},
        )
        assert r.status_code == 200
        assert "--foo" in r.text


class TestComponentRoutes:
    async def test_empty_inventory(self, client):
        r = await client.get("/projects/demo/design/components")
        assert r.status_code == 200
        assert "No components registered yet." in r.text

    async def test_register_promote_deprecate(self, client):
        r = await client.post(
            "/projects/demo/design/components",
            data={"name": "Button", "status": "proposed", "path": "ui/Button.tsx"},
        )
        assert r.status_code == 200
        assert "Button" in r.text
        assert "proposed" in r.text

        r = await client.post("/projects/demo/design/components/Button/promote")
        assert r.status_code == 200
        assert "shared" in r.text

        r = await client.post("/projects/demo/design/components/Button/deprecate")
        assert r.status_code == 200
        assert "deprecated" in r.text


class TestDesignBriefRoutes:
    async def test_empty_briefs(self, client):
        r = await client.get("/projects/demo/design/briefs")
        assert r.status_code == 200
        assert "No design briefs drafted yet." in r.text

    async def test_draft_then_approve(self, client):
        r = await client.post(
            "/projects/demo/design/briefs",
            data={
                "story_id": "S42",
                "title": "Onboarding",
                "intent": "welcome first-run user",
                "hierarchy": "primary CTA, secondary steps",
                "states": "empty / loading / error / done",
                "motion": "fade + slide",
            },
        )
        assert r.status_code == 200
        assert "Onboarding" in r.text
        assert "draft" in r.text

        r = await client.post(
            "/projects/demo/design/briefs/S42/status",
            data={"status": "ready"},
        )
        assert r.status_code == 200
        assert "ready" in r.text

        r = await client.post(
            "/projects/demo/design/briefs/S42/status",
            data={"status": "approved", "note": "looks good"},
        )
        assert r.status_code == 200
        assert "approved" in r.text
        assert "looks good" in r.text

    async def test_unknown_status_400(self, client):
        r = await client.post(
            "/projects/demo/design/briefs/S42/status",
            data={"status": "bogus"},
        )
        assert r.status_code == 400


class TestVisualRegressionRoutes:
    async def test_empty_vr(self, client):
        r = await client.get("/projects/demo/design/visual-regressions")
        assert r.status_code == 200
        assert "No visual-regression captures yet." in r.text

    async def test_capture_then_review(self, client):
        r = await client.post(
            "/projects/demo/design/visual-regressions",
            data={
                "story_id": "S42",
                "viewport": "1440x900",
                "before_path": "artifacts/before.png",
                "after_path": "artifacts/after.png",
                "mask_notes": "avatar",
            },
        )
        assert r.status_code == 200
        assert "1440x900" in r.text
        # Need to grab the entry id from the HTML (fragment includes it
        # in the form action). Simpler: hit the service to list.
        svc = client._transport.app.state.visual_regression_service
        entries = await svc.list_for_project("demo")
        assert len(entries) == 1
        entry_id = entries[0].id

        r = await client.post(
            f"/projects/demo/design/visual-regressions/{entry_id}/review",
            data={"status": "fail", "note": "hero shifted 2px"},
        )
        assert r.status_code == 200
        assert "fail" in r.text
        assert "hero shifted 2px" in r.text
        # FAIL → "blocks ship"
        assert "blocks ship" in r.text

    async def test_review_unknown_status_400(self, client):
        svc = client._transport.app.state.visual_regression_service
        from theswarm.domain.designer.value_objects import CheckStatus
        entry = await svc.capture(
            project_id="demo", story_id="S1", viewport="1440",
            before_path="b", after_path="a",
        )
        r = await client.post(
            f"/projects/demo/design/visual-regressions/{entry.id}/review",
            data={"status": "nope"},
        )
        assert r.status_code == 400
        assert CheckStatus  # keep import used


class TestAntiTemplateRoutes:
    async def test_empty_atc(self, client):
        r = await client.get("/projects/demo/design/anti-template")
        assert r.status_code == 200
        assert "No ship-bar checks recorded yet." in r.text

    async def test_record_with_auto_status_warn(self, client):
        r = await client.post(
            "/projects/demo/design/anti-template",
            data={
                "story_id": "S42",
                "pr_url": "https://github.com/a/b/pull/1",
                "qualities": "hierarchy, rhythm",
                "violations": "",
                "summary": "not quite there",
            },
        )
        assert r.status_code == 200
        # 2 qualities, 0 violations → WARN
        assert "warn" in r.text
        assert "2/4" in r.text

    async def test_record_with_auto_status_pass(self, client):
        r = await client.post(
            "/projects/demo/design/anti-template",
            data={
                "story_id": "S42",
                "qualities": "hierarchy, rhythm, depth, motion",
                "violations": "",
            },
        )
        assert r.status_code == 200
        # 4 qualities, 0 violations → PASS
        assert "pass" in r.text
        assert "4/4" in r.text

    async def test_record_with_auto_status_fail(self, client):
        r = await client.post(
            "/projects/demo/design/anti-template",
            data={
                "story_id": "S42",
                "qualities": "hierarchy, rhythm, depth, motion",
                "violations": "default-card-grid",
            },
        )
        assert r.status_code == 200
        # any violation → FAIL
        assert "fail" in r.text
