"""Phase J infrastructure tests — Writer repos."""

from __future__ import annotations

import pytest

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
    conn = await init_db(str(tmp_path / "writer.db"))
    yield conn
    await conn.close()


class TestDocArtifactRepo:
    async def test_upsert_preserves_id(self, db):
        repo = SQLiteDocArtifactRepository(db)
        d1 = DocArtifact(
            id="d1", project_id="p", kind=DocKind.README, path="README.md",
            title="First",
        )
        got1 = await repo.upsert(d1)
        d2 = DocArtifact(
            id="d2", project_id="p", kind=DocKind.README, path="README.md",
            title="Second", status=DocStatus.READY,
        )
        got2 = await repo.upsert(d2)
        assert got2.id == got1.id
        assert got2.title == "Second"
        assert got2.status == DocStatus.READY

        listed = await repo.list_for_project("p")
        assert len(listed) == 1


class TestQuickstartCheckRepo:
    async def test_add_and_list(self, db):
        repo = SQLiteQuickstartCheckRepository(db)
        q = QuickstartCheck(
            id="q1", project_id="p", step_count=5,
            duration_seconds=12.3, outcome=QuickstartOutcome.FAIL,
            failure_step="step 3: uv sync",
        )
        await repo.add(q)
        rows = await repo.list_for_project("p")
        assert len(rows) == 1
        assert rows[0].outcome == QuickstartOutcome.FAIL
        assert rows[0].failure_step == "step 3: uv sync"


class TestChangelogEntryRepo:
    async def test_add_filter_by_version(self, db):
        repo = SQLiteChangelogEntryRepository(db)
        a = ChangelogEntry(
            id="a", project_id="p", kind=ChangeKind.FEAT,
            summary="add cycles", version="1.0.0",
        )
        b = ChangelogEntry(
            id="b", project_id="p", kind=ChangeKind.FIX,
            summary="fix budget",
        )
        await repo.add(a)
        await repo.add(b)

        all_ = await repo.list_for_project("p")
        assert len(all_) == 2

        v1 = await repo.list_for_version("p", "1.0.0")
        assert len(v1) == 1
        assert v1[0].summary == "add cycles"

        unreleased = await repo.list_unreleased("p")
        assert len(unreleased) == 1
        assert unreleased[0].summary == "fix budget"
