"""Phase J application tests — Writer services."""

from __future__ import annotations

import pytest

from theswarm.application.services.writer import (
    ChangelogService,
    DocArtifactService,
    QuickstartCheckService,
)
from theswarm.domain.writer.value_objects import (
    ChangeKind,
    DocKind,
    DocStatus,
    QuickstartOutcome,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.writer.changelog_repo import (
    SQLiteChangelogEntryRepository,
)
from theswarm.infrastructure.writer.doc_repo import SQLiteDocArtifactRepository
from theswarm.infrastructure.writer.quickstart_repo import (
    SQLiteQuickstartCheckRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "writer_svc.db"))
    yield conn
    await conn.close()


class TestDocArtifactService:
    async def test_upsert_preserves_id(self, db):
        svc = DocArtifactService(SQLiteDocArtifactRepository(db))
        d1 = await svc.upsert(
            "p", path="README.md", kind=DocKind.README, title="First",
        )
        d2 = await svc.upsert(
            "p", path="README.md", kind=DocKind.README, title="Second",
        )
        assert d1.id == d2.id
        assert d2.title == "Second"

    async def test_mark_ready_sets_last_reviewed(self, db):
        svc = DocArtifactService(SQLiteDocArtifactRepository(db))
        await svc.upsert("p", path="README.md", kind=DocKind.README)
        updated = await svc.mark_status("p", "README.md", DocStatus.READY)
        assert updated.status == DocStatus.READY
        assert updated.last_reviewed_at is not None

    async def test_mark_missing_raises(self, db):
        svc = DocArtifactService(SQLiteDocArtifactRepository(db))
        with pytest.raises(ValueError):
            await svc.mark_status("p", "nope.md", DocStatus.READY)


class TestQuickstartCheckService:
    async def test_record_fail(self, db):
        svc = QuickstartCheckService(SQLiteQuickstartCheckRepository(db))
        q = await svc.record(
            "p", step_count=5, duration_seconds=10.0,
            outcome=QuickstartOutcome.FAIL, failure_step="uv sync",
        )
        assert q.is_broken
        rows = await svc.list("p")
        assert len(rows) == 1


class TestChangelogService:
    async def test_record_and_filter_by_version(self, db):
        svc = ChangelogService(SQLiteChangelogEntryRepository(db))
        await svc.record(
            "p", kind=ChangeKind.FEAT, summary="cycles", version="1.0.0",
        )
        await svc.record("p", kind=ChangeKind.FIX, summary="fix budget")
        all_ = await svc.list("p")
        assert len(all_) == 2
        v1 = await svc.list_for_version("p", "1.0.0")
        assert len(v1) == 1
        unreleased = await svc.list_unreleased("p")
        assert len(unreleased) == 1
