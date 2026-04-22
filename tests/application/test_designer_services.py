"""Phase H application-layer tests for Designer services."""

from __future__ import annotations

import pytest

from theswarm.application.services.designer import (
    AntiTemplateService,
    ComponentInventoryService,
    DesignBriefService,
    DesignSystemService,
    VisualRegressionService,
)
from theswarm.domain.designer.value_objects import (
    BriefStatus,
    CheckStatus,
    ComponentStatus,
    TokenKind,
)
from theswarm.infrastructure.designer import (
    SQLiteAntiTemplateRepository,
    SQLiteComponentRepository,
    SQLiteDesignBriefRepository,
    SQLiteDesignTokenRepository,
    SQLiteVisualRegressionRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "designer_services.db"))
    yield conn
    await conn.close()


class TestDesignSystemService:
    async def test_set_and_update_token_preserves_id(self, db):
        svc = DesignSystemService(SQLiteDesignTokenRepository(db))
        first = await svc.set_token(
            project_id="p", name="--color-accent",
            kind=TokenKind.COLOR, value="oklch(68% 0.21 250)",
        )
        again = await svc.set_token(
            project_id="p", name="--color-accent",
            kind=TokenKind.COLOR, value="oklch(60% 0.2 260)",
        )
        assert again.id == first.id
        assert again.value == "oklch(60% 0.2 260)"

    async def test_list_tokens(self, db):
        svc = DesignSystemService(SQLiteDesignTokenRepository(db))
        await svc.set_token(
            project_id="p", name="--color-accent", kind=TokenKind.COLOR,
            value="x",
        )
        await svc.set_token(
            project_id="p", name="--space-section", kind=TokenKind.SPACING,
            value="clamp(...)",
        )
        tokens = await svc.list_tokens("p")
        assert len(tokens) == 2


class TestComponentInventoryService:
    async def test_register_promote_deprecate(self, db):
        svc = ComponentInventoryService(SQLiteComponentRepository(db))
        btn = await svc.register(project_id="p", name="Button")
        assert btn.status == ComponentStatus.PROPOSED

        promoted = await svc.promote(project_id="p", name="Button")
        assert promoted is not None and promoted.status == ComponentStatus.SHARED

        dep = await svc.deprecate(project_id="p", name="Button")
        assert dep is not None and dep.status == ComponentStatus.DEPRECATED
        assert dep.is_retired is True

    async def test_bump_usage_clamps_at_zero(self, db):
        svc = ComponentInventoryService(SQLiteComponentRepository(db))
        await svc.register(project_id="p", name="Card")
        bumped = await svc.bump_usage(project_id="p", name="Card", delta=3)
        assert bumped is not None and bumped.usage_count == 3
        zeroed = await svc.bump_usage(
            project_id="p", name="Card", delta=-100,
        )
        assert zeroed is not None and zeroed.usage_count == 0

    async def test_actions_on_missing_component_return_none(self, db):
        svc = ComponentInventoryService(SQLiteComponentRepository(db))
        assert await svc.promote(project_id="p", name="X") is None
        assert await svc.deprecate(project_id="p", name="X") is None
        assert await svc.bump_usage(project_id="p", name="X") is None


class TestDesignBriefService:
    async def test_draft_then_approve_flow(self, db):
        svc = DesignBriefService(SQLiteDesignBriefRepository(db))
        draft = await svc.draft(
            project_id="p", story_id="S1",
            title="Onboarding wizard", intent="first-run tour",
        )
        assert draft.status == BriefStatus.DRAFT
        assert draft.blocks_dev is True

        ready = await svc.mark_ready(project_id="p", story_id="S1")
        assert ready is not None
        assert ready.status == BriefStatus.READY
        assert ready.blocks_dev is False

        approved = await svc.approve(
            project_id="p", story_id="S1", note="ship it",
        )
        assert approved is not None
        assert approved.is_approved is True
        assert approved.approval_note == "ship it"

    async def test_request_changes_blocks_dev(self, db):
        svc = DesignBriefService(SQLiteDesignBriefRepository(db))
        await svc.draft(project_id="p", story_id="S1", title="t")
        out = await svc.request_changes(
            project_id="p", story_id="S1", note="rework hierarchy",
        )
        assert out is not None
        assert out.status == BriefStatus.CHANGES_REQUESTED
        assert out.blocks_dev is True

    async def test_approve_missing_brief_returns_none(self, db):
        svc = DesignBriefService(SQLiteDesignBriefRepository(db))
        assert await svc.approve(project_id="p", story_id="none") is None


class TestVisualRegressionService:
    async def test_capture_and_review(self, db):
        svc = VisualRegressionService(SQLiteVisualRegressionRepository(db))
        vr = await svc.capture(
            project_id="p", story_id="S1", viewport="1440x900",
        )
        assert vr.status == CheckStatus.UNKNOWN
        reviewed = await svc.review(
            entry_id=vr.id, status=CheckStatus.FAIL, note="text cropped",
        )
        assert reviewed is not None
        assert reviewed.is_blocking is True

    async def test_list_for_story(self, db):
        svc = VisualRegressionService(SQLiteVisualRegressionRepository(db))
        await svc.capture(project_id="p", story_id="S1")
        await svc.capture(project_id="p", story_id="S1")
        entries = await svc.list_for_story("p", "S1")
        assert len(entries) == 2


class TestAntiTemplateService:
    async def test_record_auto_status(self, db):
        svc = AntiTemplateService(SQLiteAntiTemplateRepository(db))
        # four qualities, zero violations → PASS
        passed = await svc.record(
            project_id="p", story_id="S1",
            qualities=("hierarchy", "rhythm", "depth", "typography"),
        )
        assert passed.status == CheckStatus.PASS
        assert passed.passes_bar is True

        # any violation → FAIL
        failed = await svc.record(
            project_id="p", story_id="S1",
            qualities=("hierarchy", "rhythm", "depth", "typography"),
            violations=("default-card-grid",),
        )
        assert failed.status == CheckStatus.FAIL
        assert failed.passes_bar is False

        # <4 qualities, no violations → WARN
        warn = await svc.record(
            project_id="p", story_id="S1",
            qualities=("hierarchy",),
        )
        assert warn.status == CheckStatus.WARN

    async def test_latest_for_story_returns_newest(self, db):
        svc = AntiTemplateService(SQLiteAntiTemplateRepository(db))
        await svc.record(
            project_id="p", story_id="S1",
            qualities=("hierarchy",),
        )
        await svc.record(
            project_id="p", story_id="S1",
            qualities=("hierarchy", "rhythm", "depth", "typography"),
        )
        latest = await svc.latest_for_story("p", "S1")
        assert latest is not None
        assert latest.status == CheckStatus.PASS
