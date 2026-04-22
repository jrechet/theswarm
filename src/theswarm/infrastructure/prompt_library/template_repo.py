"""SQLite repository for PromptTemplate + PromptAuditEntry (Phase L)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.prompt_library.entities import (
    PromptAuditEntry,
    PromptTemplate,
)
from theswarm.domain.prompt_library.value_objects import PromptAuditAction


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLitePromptTemplateRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, t: PromptTemplate) -> PromptTemplate:
        cur = await self._db.execute(
            "SELECT id, created_at FROM prompt_templates WHERE name=?",
            (t.name,),
        )
        existing = await cur.fetchone()
        if existing:
            tmpl_id = existing["id"]
            created_at = _dt(existing["created_at"])
        else:
            tmpl_id = t.id
            created_at = t.created_at
        await self._db.execute(
            """INSERT INTO prompt_templates
                (id, name, role, body, version, deprecated, updated_by,
                 created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 role=excluded.role,
                 body=excluded.body,
                 version=excluded.version,
                 deprecated=excluded.deprecated,
                 updated_by=excluded.updated_by,
                 updated_at=excluded.updated_at""",
            (
                tmpl_id, t.name, t.role, t.body, t.version,
                1 if t.deprecated else 0, t.updated_by,
                created_at.isoformat(), t.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        return await self.get_by_name(t.name)  # type: ignore[return-value]

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        cur = await self._db.execute(
            "SELECT * FROM prompt_templates WHERE name=?", (name,),
        )
        row = await cur.fetchone()
        return _row_to_template(row) if row else None

    async def list_all(self) -> list[PromptTemplate]:
        cur = await self._db.execute(
            "SELECT * FROM prompt_templates ORDER BY name ASC",
        )
        return [_row_to_template(r) for r in await cur.fetchall()]


class SQLitePromptAuditRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, a: PromptAuditEntry) -> PromptAuditEntry:
        await self._db.execute(
            """INSERT INTO prompt_audit_entries
                (id, prompt_name, action, actor, before_version,
                 after_version, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                a.id, a.prompt_name, a.action.value, a.actor,
                a.before_version, a.after_version, a.note,
                a.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return a

    async def list_for_prompt(self, name: str) -> list[PromptAuditEntry]:
        cur = await self._db.execute(
            """SELECT * FROM prompt_audit_entries
                WHERE prompt_name=? ORDER BY created_at DESC""",
            (name,),
        )
        return [_row_to_audit(r) for r in await cur.fetchall()]

    async def list_all(self) -> list[PromptAuditEntry]:
        cur = await self._db.execute(
            "SELECT * FROM prompt_audit_entries ORDER BY created_at DESC",
        )
        return [_row_to_audit(r) for r in await cur.fetchall()]


def _row_to_template(row) -> PromptTemplate:
    return PromptTemplate(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        body=row["body"],
        version=row["version"],
        deprecated=bool(row["deprecated"]),
        updated_by=row["updated_by"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _row_to_audit(row) -> PromptAuditEntry:
    return PromptAuditEntry(
        id=row["id"],
        prompt_name=row["prompt_name"],
        action=PromptAuditAction(row["action"]),
        actor=row["actor"],
        before_version=row["before_version"],
        after_version=row["after_version"],
        note=row["note"],
        created_at=_dt(row["created_at"]),
    )
