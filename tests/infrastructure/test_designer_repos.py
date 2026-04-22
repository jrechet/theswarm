"""Phase H infrastructure tests for Designer SQLite repositories."""

from __future__ import annotations

from dataclasses import replace

import pytest

from theswarm.domain.designer.entities import (
    AntiTemplateCheck,
    ComponentEntry,
    DesignBrief,
    DesignToken,
    VisualRegression,
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
    conn = await init_db(str(tmp_path / "designer.db"))
    yield conn
    await conn.close()


class TestTokenRepo:
    async def test_upsert_and_list(self, db):
        repo = SQLiteDesignTokenRepository(db)
        await repo.upsert(DesignToken(
            id="t1", project_id="p", name="--color-accent",
            kind=TokenKind.COLOR, value="oklch(68% 0.21 250)",
        ))
        # update same (project, name) → single row
        await repo.upsert(DesignToken(
            id="t_other", project_id="p", name="--color-accent",
            kind=TokenKind.COLOR, value="oklch(60% 0.2 260)",
        ))
        tokens = await repo.list_for_project("p")
        assert len(tokens) == 1
        assert tokens[0].value == "oklch(60% 0.2 260)"


class TestComponentRepo:
    async def test_upsert_and_active_only_filter(self, db):
        repo = SQLiteComponentRepository(db)
        await repo.upsert(ComponentEntry(
            id="c1", project_id="p", name="Button",
            status=ComponentStatus.SHARED,
        ))
        await repo.upsert(ComponentEntry(
            id="c2", project_id="p", name="OldCard",
            status=ComponentStatus.LEGACY,
        ))
        all_ = await repo.list_for_project("p")
        assert len(all_) == 2
        active = await repo.list_for_project("p", active_only=True)
        names = {c.name for c in active}
        assert names == {"Button"}


class TestBriefRepo:
    async def test_upsert_by_story_id(self, db):
        repo = SQLiteDesignBriefRepository(db)
        await repo.upsert(DesignBrief(
            id="b1", project_id="p", story_id="S1",
            title="Add onboarding", intent="welcome new user",
            status=BriefStatus.DRAFT,
        ))
        # second upsert for same (project, story) overwrites
        await repo.upsert(DesignBrief(
            id="b2", project_id="p", story_id="S1",
            title="Add onboarding v2", intent="v2",
            status=BriefStatus.READY,
        ))
        got = await repo.get_for_story("p", "S1")
        assert got is not None
        assert got.title == "Add onboarding v2"
        assert got.status == BriefStatus.READY

    async def test_list_newest_first(self, db):
        repo = SQLiteDesignBriefRepository(db)
        b1 = DesignBrief(id="b1", project_id="p", story_id="S1", title="first")
        await repo.upsert(b1)
        b2 = DesignBrief(id="b2", project_id="p", story_id="S2", title="second")
        await repo.upsert(b2)
        listed = await repo.list_for_project("p")
        assert len(listed) == 2
        assert listed[0].story_id == "S2"


class TestVisualRegressionRepo:
    async def test_add_and_review(self, db):
        repo = SQLiteVisualRegressionRepository(db)
        await repo.add(VisualRegression(
            id="v1", project_id="p", story_id="S1", viewport="1440x900",
        ))
        await repo.review(
            "v1", status=CheckStatus.FAIL, reviewer_note="hierarchy broke",
        )
        got = await repo.get("v1")
        assert got is not None
        assert got.status == CheckStatus.FAIL
        assert got.is_blocking is True

    async def test_list_for_story(self, db):
        repo = SQLiteVisualRegressionRepository(db)
        await repo.add(VisualRegression(id="v1", project_id="p", story_id="S1"))
        await repo.add(VisualRegression(id="v2", project_id="p", story_id="S1"))
        await repo.add(VisualRegression(id="v3", project_id="p", story_id="S2"))
        s1 = await repo.list_for_story("p", "S1")
        assert len(s1) == 2


class TestAntiTemplateRepo:
    async def test_add_and_latest_for_story(self, db):
        repo = SQLiteAntiTemplateRepository(db)
        await repo.add(AntiTemplateCheck(
            id="a1", project_id="p", story_id="S1",
            status=CheckStatus.WARN,
            qualities=("hierarchy", "rhythm"),
            violations=("default-card-grid",),
        ))
        await repo.add(AntiTemplateCheck(
            id="a2", project_id="p", story_id="S1",
            status=CheckStatus.PASS,
            qualities=("hierarchy", "rhythm", "depth", "typography"),
        ))
        latest = await repo.latest_for_story("p", "S1")
        assert latest is not None
        assert latest.id == "a2"
        assert latest.status == CheckStatus.PASS
        assert latest.passes_bar is True

    async def test_list_preserves_qualities_and_violations(self, db):
        repo = SQLiteAntiTemplateRepository(db)
        await repo.add(AntiTemplateCheck(
            id="a1", project_id="p", story_id="S1",
            qualities=("hierarchy", "motion"),
            violations=("stock-hero",),
        ))
        [entry] = await repo.list_for_project("p")
        assert entry.qualities == ("hierarchy", "motion")
        assert entry.violations == ("stock-hero",)
