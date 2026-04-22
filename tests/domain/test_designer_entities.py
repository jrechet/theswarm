"""Phase H domain tests for Designer entities."""

from __future__ import annotations

from dataclasses import replace

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


class TestDesignToken:
    def test_is_frozen(self):
        t = DesignToken(
            id=DesignToken.new_id(), project_id="p",
            name="--color-accent", kind=TokenKind.COLOR, value="oklch(68% 0.21 250)",
        )
        # round-trip via replace
        t2 = replace(t, value="oklch(60% 0.2 260)")
        assert t2.value == "oklch(60% 0.2 260)"
        assert t.value == "oklch(68% 0.21 250)"

    def test_new_id_has_prefix(self):
        assert DesignToken.new_id().startswith("tok_")


class TestComponentEntry:
    def test_is_shared_and_is_retired(self):
        proposed = ComponentEntry(
            id="c1", project_id="p", name="Button",
            status=ComponentStatus.PROPOSED,
        )
        shared = replace(proposed, status=ComponentStatus.SHARED)
        legacy = replace(proposed, status=ComponentStatus.LEGACY)
        deprecated = replace(proposed, status=ComponentStatus.DEPRECATED)

        assert proposed.is_shared is False
        assert shared.is_shared is True
        assert proposed.is_retired is False
        assert legacy.is_retired is True
        assert deprecated.is_retired is True


class TestDesignBrief:
    def test_blocks_dev_until_ready(self):
        draft = DesignBrief(id="b1", project_id="p", status=BriefStatus.DRAFT)
        ready = replace(draft, status=BriefStatus.READY)
        approved = replace(draft, status=BriefStatus.APPROVED)
        changes = replace(draft, status=BriefStatus.CHANGES_REQUESTED)

        assert draft.blocks_dev is True
        assert changes.blocks_dev is True
        assert ready.blocks_dev is False
        assert approved.blocks_dev is False
        assert approved.is_approved is True
        assert ready.is_approved is False


class TestVisualRegression:
    def test_is_blocking_only_when_fail(self):
        base = VisualRegression(id="v1", project_id="p")
        assert base.is_blocking is False  # UNKNOWN
        failed = replace(base, status=CheckStatus.FAIL)
        passed = replace(base, status=CheckStatus.PASS)
        warn = replace(base, status=CheckStatus.WARN)
        assert failed.is_blocking is True
        assert passed.is_blocking is False
        assert warn.is_blocking is False


class TestAntiTemplateCheck:
    def test_passes_bar_requires_four_qualities_and_zero_violations(self):
        empty = AntiTemplateCheck(id="a1", project_id="p")
        assert empty.quality_count == 0
        assert empty.passes_bar is False

        three = replace(empty, qualities=("hierarchy", "rhythm", "depth"))
        assert three.quality_count == 3
        assert three.passes_bar is False  # below threshold

        four = replace(empty, qualities=(
            "hierarchy", "rhythm", "depth", "typography",
        ))
        assert four.quality_count == 4
        assert four.passes_bar is True

        with_violation = replace(four, violations=("default-card-grid",))
        assert with_violation.passes_bar is False

    def test_threshold_constant(self):
        assert AntiTemplateCheck.REQUIRED_QUALITIES == 4
