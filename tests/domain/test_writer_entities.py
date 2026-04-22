"""Phase J domain tests — Writer entities."""

from __future__ import annotations

from theswarm.domain.writer.entities import (
    ChangelogEntry,
    DocArtifact,
    QuickstartCheck,
)
from theswarm.domain.writer.value_objects import (
    ChangeKind,
    DocKind,
    DocStatus,
    QuickstartOutcome,
)


class TestDocArtifact:
    def test_defaults(self):
        d = DocArtifact(
            id="d1", project_id="p", kind=DocKind.README, path="README.md",
        )
        assert d.status == DocStatus.DRAFT
        assert d.last_reviewed_at is None
        assert not d.needs_refresh

    def test_stale_needs_refresh(self):
        d = DocArtifact(
            id="d1", project_id="p", kind=DocKind.README, path="README.md",
            status=DocStatus.STALE,
        )
        assert d.needs_refresh


class TestQuickstartCheck:
    def test_fail_is_broken(self):
        q = QuickstartCheck(
            id="q1", project_id="p", step_count=5,
            outcome=QuickstartOutcome.FAIL, failure_step="step 3",
        )
        assert q.is_broken

    def test_pass_not_broken(self):
        q = QuickstartCheck(
            id="q1", project_id="p",
            outcome=QuickstartOutcome.PASS,
        )
        assert not q.is_broken


class TestChangelogEntry:
    def test_breaking_is_flagged(self):
        c = ChangelogEntry(
            id="c1", project_id="p", kind=ChangeKind.BREAKING,
            summary="drop legacy endpoint",
        )
        assert c.is_breaking

    def test_feat_not_breaking(self):
        c = ChangelogEntry(
            id="c1", project_id="p", kind=ChangeKind.FEAT,
            summary="add new endpoint",
        )
        assert not c.is_breaking
