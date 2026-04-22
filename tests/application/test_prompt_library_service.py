"""Phase L application tests — prompt library service."""

from __future__ import annotations

import pytest

from theswarm.application.services.prompt_library import PromptLibraryService
from theswarm.domain.prompt_library.value_objects import PromptAuditAction
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.prompt_library.template_repo import (
    SQLitePromptAuditRepository,
    SQLitePromptTemplateRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "prompts_svc.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def svc(db):
    return PromptLibraryService(
        SQLitePromptTemplateRepository(db),
        SQLitePromptAuditRepository(db),
    )


class TestPromptLibraryService:
    async def test_create_emits_create_audit(self, svc):
        t = await svc.upsert(
            name="po.morning", body="hi", role="po",
            actor="alice", note="initial",
        )
        assert t.version == 1
        entries = await svc.list_audit(name="po.morning")
        assert len(entries) == 1
        assert entries[0].action == PromptAuditAction.CREATE
        assert entries[0].after_version == 1
        assert entries[0].note == "initial"

    async def test_update_bumps_version_and_audits(self, svc):
        await svc.upsert(name="x", body="a", role="po")
        t = await svc.upsert(name="x", body="b", role="po", actor="alice")
        assert t.version == 2
        entries = await svc.list_audit(name="x")
        actions = [e.action for e in entries]
        # most recent first — at least one UPDATE
        assert PromptAuditAction.UPDATE in actions

    async def test_idempotent_save_does_not_bump(self, svc):
        t0 = await svc.upsert(name="x", body="a", role="po")
        t1 = await svc.upsert(name="x", body="a", role="po")
        assert t1.version == t0.version == 1
        entries = await svc.list_audit(name="x")
        # only the CREATE entry — no UPDATE for a noop save
        assert len(entries) == 1
        assert entries[0].action == PromptAuditAction.CREATE

    async def test_role_change_bumps_version(self, svc):
        await svc.upsert(name="x", body="a", role="po")
        t = await svc.upsert(name="x", body="a", role="techlead")
        assert t.version == 2

    async def test_deprecate_and_restore(self, svc):
        await svc.upsert(name="x", body="a")
        t = await svc.deprecate("x", actor="alice", note="stale")
        assert t.deprecated is True
        t = await svc.restore("x", actor="alice")
        assert t.deprecated is False
        actions = [e.action for e in await svc.list_audit(name="x")]
        assert PromptAuditAction.DEPRECATE in actions
        assert PromptAuditAction.RESTORE in actions

    async def test_deprecate_missing_raises(self, svc):
        with pytest.raises(ValueError):
            await svc.deprecate("missing")

    async def test_restore_missing_raises(self, svc):
        with pytest.raises(ValueError):
            await svc.restore("missing")

    async def test_deprecate_idempotent_audits_once(self, svc):
        await svc.upsert(name="x")
        await svc.deprecate("x", actor="a")
        await svc.deprecate("x", actor="a")  # no-op
        deprecate_entries = [
            e for e in await svc.list_audit(name="x")
            if e.action == PromptAuditAction.DEPRECATE
        ]
        assert len(deprecate_entries) == 1

    async def test_note_only_save_is_noop(self, svc):
        """Note/actor changes without body or role delta must not audit silently."""
        t0 = await svc.upsert(name="x", body="a", role="po", actor="alice")
        t1 = await svc.upsert(
            name="x", body="a", role="po", actor="bob", note="trying to change",
        )
        assert t1.version == t0.version == 1
        # updated_by must not change — no real mutation occurred
        assert t1.updated_by == "alice"
        entries = await svc.list_audit(name="x")
        assert len(entries) == 1
        assert entries[0].action == PromptAuditAction.CREATE

    async def test_list_audit_all(self, svc):
        await svc.upsert(name="a")
        await svc.upsert(name="b")
        entries = await svc.list_audit()
        names = {e.prompt_name for e in entries}
        assert names == {"a", "b"}
