"""Phase L infra tests — prompt library repos."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.prompt_library.entities import (
    PromptAuditEntry,
    PromptTemplate,
)
from theswarm.domain.prompt_library.value_objects import PromptAuditAction
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.prompt_library.template_repo import (
    SQLitePromptAuditRepository,
    SQLitePromptTemplateRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "prompts.db"))
    yield conn
    await conn.close()


class TestPromptTemplateRepo:
    async def test_upsert_and_get(self, db):
        repo = SQLitePromptTemplateRepository(db)
        t = PromptTemplate(
            id="t1", name="po.morning", role="po", body="hello",
            version=1,
        )
        await repo.upsert(t)
        got = await repo.get_by_name("po.morning")
        assert got is not None
        assert got.role == "po"
        assert got.body == "hello"
        assert got.version == 1

    async def test_upsert_preserves_id_and_created_at(self, db):
        repo = SQLitePromptTemplateRepository(db)
        t0 = PromptTemplate(
            id="t1", name="x", body="a", version=1,
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        await repo.upsert(t0)
        original = await repo.get_by_name("x")
        assert original is not None
        # upsert with a different id + created_at should not overwrite
        t1 = PromptTemplate(
            id="t2", name="x", body="b", version=2,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        await repo.upsert(t1)
        updated = await repo.get_by_name("x")
        assert updated is not None
        assert updated.id == original.id
        assert updated.created_at == original.created_at
        assert updated.body == "b"
        assert updated.version == 2

    async def test_list_all_sorted(self, db):
        repo = SQLitePromptTemplateRepository(db)
        await repo.upsert(PromptTemplate(id="t1", name="zeta"))
        await repo.upsert(PromptTemplate(id="t2", name="alpha"))
        rows = await repo.list_all()
        assert [r.name for r in rows] == ["alpha", "zeta"]


class TestPromptAuditRepo:
    async def test_add_and_list_for_prompt(self, db):
        repo = SQLitePromptAuditRepository(db)
        a = PromptAuditEntry(
            id="a1", prompt_name="x", action=PromptAuditAction.CREATE,
            actor="alice", after_version=1, note="created",
        )
        await repo.add(a)
        rows = await repo.list_for_prompt("x")
        assert len(rows) == 1
        assert rows[0].note == "created"
        assert rows[0].action == PromptAuditAction.CREATE

    async def test_list_all_orders_desc(self, db):
        repo = SQLitePromptAuditRepository(db)
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2024, 6, 1, tzinfo=timezone.utc)
        await repo.add(PromptAuditEntry(
            id="a1", prompt_name="x", action=PromptAuditAction.CREATE,
            after_version=1, created_at=t0,
        ))
        await repo.add(PromptAuditEntry(
            id="a2", prompt_name="y", action=PromptAuditAction.CREATE,
            after_version=1, created_at=t1,
        ))
        rows = await repo.list_all()
        assert [r.id for r in rows] == ["a2", "a1"]
