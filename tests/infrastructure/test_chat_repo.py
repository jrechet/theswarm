"""Tests for SQLiteChatRepository + SQLiteHITLAuditRepository (Phase B)."""

from __future__ import annotations

import pytest

from theswarm.domain.chat.threads import AuthorKind, ChatMessage, ChatThread
from theswarm.infrastructure.chat.chat_repo import (
    SQLiteChatRepository,
    SQLiteHITLAuditRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "chat.db"))
    yield conn
    await conn.close()


class TestSQLiteChatRepository:
    async def test_get_or_create_thread_is_idempotent(self, db):
        repo = SQLiteChatRepository(db)
        a = await repo.get_or_create_thread(project_id="demo", codename="Mei", role="po")
        b = await repo.get_or_create_thread(project_id="demo", codename="Mei", role="po")
        assert a.id == b.id

    async def test_append_and_list_messages(self, db):
        repo = SQLiteChatRepository(db)
        t = await repo.get_or_create_thread(project_id="demo")
        m1 = await repo.append_message(
            ChatMessage(
                id=ChatMessage.new_id(),
                thread_id=t.id,
                author_kind=AuthorKind.HUMAN,
                body="ping",
            ),
        )
        m2 = await repo.append_message(
            ChatMessage(
                id=ChatMessage.new_id(),
                thread_id=t.id,
                author_kind=AuthorKind.AGENT,
                body="pong",
            ),
        )
        msgs = await repo.list_messages(t.id)
        assert [m.id for m in msgs] == [m1.id, m2.id]

    async def test_append_updates_message_count(self, db):
        repo = SQLiteChatRepository(db)
        t = await repo.get_or_create_thread(project_id="demo")
        for _ in range(3):
            await repo.append_message(ChatMessage(
                id=ChatMessage.new_id(),
                thread_id=t.id,
                author_kind=AuthorKind.HUMAN,
                body="x",
            ))
        reloaded = await repo.get_thread(t.id)
        assert reloaded.message_count == 3

    async def test_list_threads_filters_by_project(self, db):
        repo = SQLiteChatRepository(db)
        await repo.get_or_create_thread(project_id="a")
        await repo.get_or_create_thread(project_id="b")
        only_a = await repo.list_threads(project_id="a")
        assert len(only_a) == 1
        assert only_a[0].project_id == "a"
        all_threads = await repo.list_threads()
        assert len(all_threads) == 2

    async def test_list_messages_after_filter(self, db):
        repo = SQLiteChatRepository(db)
        t = await repo.get_or_create_thread(project_id="demo")
        m1 = await repo.append_message(ChatMessage(
            id=ChatMessage.new_id(),
            thread_id=t.id,
            author_kind=AuthorKind.HUMAN,
            body="first",
        ))
        m2 = await repo.append_message(ChatMessage(
            id=ChatMessage.new_id(),
            thread_id=t.id,
            author_kind=AuthorKind.AGENT,
            body="second",
        ))
        after = await repo.list_messages(t.id, after=m1.created_at)
        assert [m.id for m in after] == [m2.id]

    async def test_get_thread_missing_returns_none(self, db):
        repo = SQLiteChatRepository(db)
        assert await repo.get_thread("nope") is None


class TestSQLiteHITLAuditRepository:
    async def test_record_and_list(self, db):
        repo = SQLiteHITLAuditRepository(db)
        audit_id = await repo.record(
            project_id="demo",
            cycle_id="c1",
            action="nudge",
            note="push harder on tests",
        )
        assert audit_id.startswith("au_")
        entries = await repo.list_for_project("demo")
        assert len(entries) == 1
        assert entries[0]["action"] == "nudge"
        assert entries[0]["note"] == "push harder on tests"

    async def test_list_recent_crosses_projects(self, db):
        repo = SQLiteHITLAuditRepository(db)
        await repo.record(project_id="a", action="pause")
        await repo.record(project_id="b", action="skip")
        recent = await repo.list_recent()
        projects = {e["project_id"] for e in recent}
        assert projects == {"a", "b"}

    async def test_metadata_roundtrip(self, db):
        repo = SQLiteHITLAuditRepository(db)
        await repo.record(
            project_id="demo", action="override",
            metadata={"phase": "qa", "k": 1},
        )
        entries = await repo.list_recent()
        assert entries[0]["metadata"] == {"phase": "qa", "k": 1}
