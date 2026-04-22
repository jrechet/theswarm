"""SQLite repositories for dashboard chat threads, messages, and HITL audit."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.chat.threads import AuthorKind, ChatMessage, ChatThread


def _parse_ts(raw: str) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime.now(timezone.utc)


def _iso(ts: datetime | None) -> str:
    if ts is None:
        return ""
    return ts.isoformat()


class SQLiteChatRepository:
    """Persist chat threads and messages."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert_thread(self, thread: ChatThread) -> None:
        await self._db.execute(
            """
            INSERT INTO chat_threads
                (id, project_id, codename, role, title, created_at,
                 last_message_at, message_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                last_message_at = excluded.last_message_at,
                message_count = excluded.message_count,
                role = excluded.role
            """,
            (
                thread.id,
                thread.project_id,
                thread.codename,
                thread.role,
                thread.title,
                thread.created_at.isoformat(),
                _iso(thread.last_message_at),
                thread.message_count,
            ),
        )
        await self._db.commit()

    async def get_thread(self, thread_id: str) -> ChatThread | None:
        cursor = await self._db.execute(
            "SELECT * FROM chat_threads WHERE id = ?", (thread_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_thread(row)

    async def get_or_create_thread(
        self,
        project_id: str,
        codename: str = "",
        role: str = "",
        title: str = "",
    ) -> ChatThread:
        thread_id = ChatThread.deterministic_id(project_id, codename)
        existing = await self.get_thread(thread_id)
        if existing is not None:
            return existing
        thread = ChatThread(
            id=thread_id,
            project_id=project_id,
            codename=codename,
            role=role,
            title=title,
        )
        await self.upsert_thread(thread)
        return thread

    async def list_threads(self, project_id: str | None = None) -> list[ChatThread]:
        if project_id is None:
            cursor = await self._db.execute(
                "SELECT * FROM chat_threads ORDER BY last_message_at DESC, created_at DESC",
            )
        else:
            cursor = await self._db.execute(
                """SELECT * FROM chat_threads
                   WHERE project_id = ?
                   ORDER BY last_message_at DESC, created_at DESC""",
                (project_id,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_thread(r) for r in rows]

    async def append_message(self, message: ChatMessage) -> ChatMessage:
        await self._db.execute(
            """
            INSERT INTO chat_messages
                (id, thread_id, author_kind, author_id, author_display,
                 body, intent_action, intent_confidence, reply_to,
                 created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.thread_id,
                message.author_kind.value,
                message.author_id,
                message.author_display,
                message.body,
                message.intent_action,
                message.intent_confidence,
                message.reply_to,
                message.created_at.isoformat(),
                json.dumps(message.metadata),
            ),
        )
        await self._db.execute(
            """UPDATE chat_threads
               SET last_message_at = ?, message_count = message_count + 1
               WHERE id = ?""",
            (message.created_at.isoformat(), message.thread_id),
        )
        await self._db.commit()
        return message

    async def list_messages(
        self,
        thread_id: str,
        limit: int = 200,
        after: datetime | None = None,
    ) -> list[ChatMessage]:
        if after is None:
            cursor = await self._db.execute(
                """SELECT * FROM chat_messages
                   WHERE thread_id = ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (thread_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """SELECT * FROM chat_messages
                   WHERE thread_id = ? AND created_at > ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (thread_id, after.isoformat(), limit),
            )
        rows = await cursor.fetchall()
        return [self._row_to_message(r) for r in rows]

    def _row_to_thread(self, row) -> ChatThread:
        last = row["last_message_at"]
        return ChatThread(
            id=row["id"],
            project_id=row["project_id"],
            codename=row["codename"],
            role=row["role"],
            title=row["title"],
            created_at=_parse_ts(row["created_at"]),
            last_message_at=_parse_ts(last) if last else None,
            message_count=row["message_count"] or 0,
        )

    def _row_to_message(self, row) -> ChatMessage:
        metadata_raw = row["metadata_json"] or "{}"
        try:
            metadata = json.loads(metadata_raw)
        except (TypeError, ValueError):
            metadata = {}
        return ChatMessage(
            id=row["id"],
            thread_id=row["thread_id"],
            author_kind=AuthorKind(row["author_kind"]),
            author_id=row["author_id"],
            author_display=row["author_display"],
            body=row["body"],
            intent_action=row["intent_action"],
            intent_confidence=row["intent_confidence"] or 0.0,
            reply_to=row["reply_to"],
            created_at=_parse_ts(row["created_at"]),
            metadata=metadata,
        )


class SQLiteHITLAuditRepository:
    """Persist human-in-the-loop interventions (nudge, pause, skip, override)."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def record(
        self,
        *,
        project_id: str,
        action: str,
        cycle_id: str = "",
        actor: str = "human",
        target: str = "",
        note: str = "",
        metadata: dict | None = None,
    ) -> str:
        audit_id = f"au_{uuid.uuid4().hex[:12]}"
        await self._db.execute(
            """
            INSERT INTO hitl_audit
                (id, project_id, cycle_id, actor, action, target, note,
                 created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                project_id,
                cycle_id,
                actor,
                action,
                target,
                note,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(metadata or {}),
            ),
        )
        await self._db.commit()
        return audit_id

    async def list_for_project(
        self, project_id: str, limit: int = 200,
    ) -> list[dict]:
        cursor = await self._db.execute(
            """SELECT * FROM hitl_audit
               WHERE project_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def list_recent(self, limit: int = 200) -> list[dict]:
        cursor = await self._db.execute(
            """SELECT * FROM hitl_audit
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _row_to_dict(self, row) -> dict:
        metadata_raw = row["metadata_json"] or "{}"
        try:
            metadata = json.loads(metadata_raw)
        except (TypeError, ValueError):
            metadata = {}
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "cycle_id": row["cycle_id"],
            "actor": row["actor"],
            "action": row["action"],
            "target": row["target"],
            "note": row["note"],
            "created_at": row["created_at"],
            "metadata": metadata,
        }
