"""SQLite repository for design tokens."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.designer.entities import DesignToken
from theswarm.domain.designer.value_objects import TokenKind


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteDesignTokenRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, token: DesignToken) -> DesignToken:
        existing = await self.get_for_name(token.project_id, token.name)
        if existing is None:
            await self._db.execute(
                """INSERT INTO design_tokens
                    (id, project_id, name, kind, value, notes,
                     created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    token.id,
                    token.project_id,
                    token.name,
                    token.kind.value,
                    token.value,
                    token.notes,
                    token.created_at.isoformat(),
                    token.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE design_tokens
                      SET kind=?, value=?, notes=?, updated_at=?
                    WHERE id=?""",
                (
                    token.kind.value,
                    token.value,
                    token.notes,
                    token.updated_at.isoformat(),
                    existing.id,
                ),
            )
        await self._db.commit()
        saved = await self.get_for_name(token.project_id, token.name)
        assert saved is not None
        return saved

    async def get_for_name(
        self, project_id: str, name: str,
    ) -> DesignToken | None:
        cur = await self._db.execute(
            "SELECT * FROM design_tokens WHERE project_id=? AND name=?",
            (project_id, name),
        )
        row = await cur.fetchone()
        return _row_to_token(row) if row else None

    async def list_for_project(self, project_id: str) -> list[DesignToken]:
        cur = await self._db.execute(
            "SELECT * FROM design_tokens WHERE project_id=? ORDER BY kind, name",
            (project_id,),
        )
        return [_row_to_token(r) for r in await cur.fetchall()]

    async def delete(self, token_id: str) -> None:
        await self._db.execute(
            "DELETE FROM design_tokens WHERE id=?", (token_id,),
        )
        await self._db.commit()


def _row_to_token(row) -> DesignToken:
    return DesignToken(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        kind=TokenKind(row["kind"]),
        value=row["value"],
        notes=row["notes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
