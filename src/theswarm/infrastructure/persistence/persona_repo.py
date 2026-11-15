"""The personas (migration v043)."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from theswarm.domain.agents.persona import Persona


class SQLitePersonaRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def list_all(self) -> list[Persona]:
        cursor = await self._db.execute("SELECT * FROM personas ORDER BY scope, key")
        out: list[Persona] = []
        for row in await cursor.fetchall():
            try:
                out.append(Persona(
                    scope=row["scope"], key=row["key"], name=row["name"], description=row["description"],
                    instructions=row["instructions"], model=row["model"], effort=row["effort"],
                    updated_by=row["updated_by"], updated_at=datetime.fromisoformat(row["updated_at"]),
                ))
            except ValueError:  # a row another version wrote: ignored, not fatal
                continue
        return out

    async def save(self, persona: Persona) -> None:
        await self._db.execute(
            """INSERT INTO personas (scope, key, name, description, instructions, model, effort, updated_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(scope, key) DO UPDATE SET name = excluded.name, description = excluded.description,
                 instructions = excluded.instructions, model = excluded.model, effort = excluded.effort,
                 updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
            (persona.scope, persona.key, persona.name, persona.description, persona.instructions, persona.model,
             persona.effort, persona.updated_by, persona.updated_at.isoformat()),
        )
        await self._db.commit()

    async def delete(self, scope: str, key: str) -> None:
        await self._db.execute("DELETE FROM personas WHERE scope = ? AND key = ?", (scope, key))
        await self._db.commit()
