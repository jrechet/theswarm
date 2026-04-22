"""Phase L application tests — semantic memory service."""

from __future__ import annotations

import pytest

from theswarm.application.services.semantic_memory import (
    SemanticMemoryService,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.semantic_memory.entry_repo import (
    SQLiteSemanticMemoryRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "mem_svc.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def svc(db):
    return SemanticMemoryService(SQLiteSemanticMemoryRepository(db))


class TestSemanticMemoryService:
    async def test_record_normalises_tags(self, svc):
        e = await svc.record(
            title="t", tags=("Security", " security ", "Auth"),
        )
        assert e.tags == ("security", "auth")

    async def test_set_enabled_toggles(self, svc):
        e = await svc.record(title="t", enabled=True)
        e = await svc.set_enabled(e.id, False)
        assert e.enabled is False
        e = await svc.set_enabled(e.id, True)
        assert e.enabled is True

    async def test_set_enabled_missing_raises(self, svc):
        with pytest.raises(ValueError):
            await svc.set_enabled("missing", False)

    async def test_search_excludes_disabled(self, svc):
        await svc.record(title="enabled auth", tags=("auth",))
        await svc.record(
            title="disabled auth", tags=("auth",), enabled=False,
        )
        hits = await svc.search(query="auth")
        titles = {h.title for h in hits}
        assert titles == {"enabled auth"}

    async def test_search_by_tag(self, svc):
        await svc.record(title="a", tags=("security",))
        await svc.record(title="b", tags=("design",))
        hits = await svc.search(tag="security")
        assert {h.title for h in hits} == {"a"}

    async def test_search_project_scoped_includes_portfolio(self, svc):
        await svc.record(title="portfolio", project_id="")
        await svc.record(title="p1-entry", project_id="p1")
        await svc.record(title="p2-entry", project_id="p2")
        hits = await svc.search(project_id="p1")
        titles = {h.title for h in hits}
        assert "portfolio" in titles
        assert "p1-entry" in titles
        assert "p2-entry" not in titles
