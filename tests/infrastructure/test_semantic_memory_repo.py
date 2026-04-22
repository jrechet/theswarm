"""Phase L infra tests — semantic memory repo."""

from __future__ import annotations

import pytest

from theswarm.domain.semantic_memory.entities import SemanticMemoryEntry
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.semantic_memory.entry_repo import (
    SQLiteSemanticMemoryRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "memory.db"))
    yield conn
    await conn.close()


class TestSemanticMemoryRepo:
    async def test_add_and_get(self, db):
        repo = SQLiteSemanticMemoryRepository(db)
        e = SemanticMemoryEntry(
            id="e1", project_id="", title="t", content="c",
            tags=("a", "b"), enabled=True,
        )
        await repo.add(e)
        got = await repo.get_by_id("e1")
        assert got is not None
        assert got.tags == ("a", "b")
        assert got.enabled is True

    async def test_list_project_scoped_includes_portfolio(self, db):
        repo = SQLiteSemanticMemoryRepository(db)
        await repo.add(SemanticMemoryEntry(
            id="e1", project_id="", title="portfolio", content="",
        ))
        await repo.add(SemanticMemoryEntry(
            id="e2", project_id="p1", title="project", content="",
        ))
        await repo.add(SemanticMemoryEntry(
            id="e3", project_id="p2", title="other", content="",
        ))
        rows = await repo.list_all(project_id="p1")
        titles = {r.title for r in rows}
        assert "portfolio" in titles
        assert "project" in titles
        assert "other" not in titles

    async def test_update_persists_enabled_flag(self, db):
        repo = SQLiteSemanticMemoryRepository(db)
        e = SemanticMemoryEntry(
            id="e1", project_id="", title="x", content="",
            enabled=True,
        )
        await repo.add(e)
        from dataclasses import replace
        disabled = replace(e, enabled=False)
        await repo.update(disabled)
        got = await repo.get_by_id("e1")
        assert got is not None
        assert got.enabled is False
