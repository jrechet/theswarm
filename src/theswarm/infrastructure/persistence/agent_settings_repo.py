"""The owner's per-persona Claude settings (migration v037)."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from theswarm.domain.agents.settings import AgentSetting


class SQLiteAgentSettingsRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def list_all(self) -> dict[str, AgentSetting]:
        cursor = await self._db.execute("SELECT * FROM agent_settings")
        out = {}
        for row in await cursor.fetchall():
            try:
                out[row["persona"]] = AgentSetting(
                    persona=row["persona"], model=row["model"], effort=row["effort"],
                    updated_by=row["updated_by"], updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            except ValueError:  # a row an older or newer version wrote: ignored, not fatal
                continue
        return out

    async def save(self, setting: AgentSetting) -> None:
        await self._db.execute(
            """INSERT INTO agent_settings (persona, model, effort, updated_by, updated_at) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(persona) DO UPDATE SET model = excluded.model, effort = excluded.effort,
                 updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
            (setting.persona, setting.model, setting.effort, setting.updated_by, setting.updated_at.isoformat()),
        )
        await self._db.commit()

    async def delete(self, persona: str) -> None:
        await self._db.execute("DELETE FROM agent_settings WHERE persona = ?", (persona,))
        await self._db.commit()
