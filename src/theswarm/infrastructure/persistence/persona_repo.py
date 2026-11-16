"""The personas (migration v043)."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from theswarm.domain.agents.persona import Persona
from theswarm.domain.teams.extras import Extra


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

    async def replace_scope(self, scope: str, personas: list[Persona]) -> None:
        """Every persona of `scope` at once (an import): the ones not given go."""
        await self._db.execute("DELETE FROM personas WHERE scope = ?", (scope,))
        for persona in personas:
            await self._db.execute(
                """INSERT INTO personas (scope, key, name, description, instructions, model, effort, updated_by, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (persona.scope, persona.key, persona.name, persona.description, persona.instructions, persona.model,
                 persona.effort, persona.updated_by, persona.updated_at.isoformat()),
            )
        await self._db.commit()

    # ── versions (v044) ──
    async def add_version(self, scope: str, body: str, by: str, at: str) -> int:
        cursor = await self._db.execute("SELECT COALESCE(MAX(version), 0) FROM team_versions WHERE scope = ?", (scope,))
        version = int((await cursor.fetchone())[0]) + 1
        await self._db.execute(
            "INSERT INTO team_versions (scope, version, body, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (scope, version, body, by, at),
        )
        await self._db.commit()
        return version

    async def versions(self, scope: str, limit: int = 20) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT version, body, created_by, created_at FROM team_versions WHERE scope = ? ORDER BY version DESC LIMIT ?",
            (scope, limit),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def latest_versions(self) -> dict[str, int]:
        cursor = await self._db.execute("SELECT scope, MAX(version) AS version FROM team_versions GROUP BY scope")
        return {row["scope"]: int(row["version"]) for row in await cursor.fetchall()}

    # ── the team a cycle started with (v044) ──
    async def pinned(self, thread_id: str) -> dict | None:
        cursor = await self._db.execute("SELECT project, label, team FROM cycle_teams WHERE thread_id = ?", (thread_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def pin(self, thread_id: str, project: str, label: str, team: str, at: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO cycle_teams (thread_id, project, label, team, pinned_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, project, label, team, at),
        )
        await self._db.commit()

    # ── free personas (v045) ──
    async def list_extras(self) -> list[Extra]:
        cursor = await self._db.execute("SELECT * FROM team_extras ORDER BY scope, key")
        out: list[Extra] = []
        for row in await cursor.fetchall():
            try:
                out.append(Extra(
                    scope=row["scope"], key=row["key"], name=row["name"], prompt=row["prompt"], point=row["point"],
                    effect=row["effect"], model=row["model"], enabled=bool(row["enabled"]),
                    updated_by=row["updated_by"], updated_at=datetime.fromisoformat(row["updated_at"]),
                ))
            except ValueError:  # a row another version wrote: ignored, not fatal
                continue
        return out

    async def save_extra(self, extra: Extra) -> None:
        await self._db.execute(
            """INSERT INTO team_extras (scope, key, name, prompt, point, effect, model, enabled, updated_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(scope, key) DO UPDATE SET name = excluded.name, prompt = excluded.prompt,
                 point = excluded.point, effect = excluded.effect, model = excluded.model, enabled = excluded.enabled,
                 updated_by = excluded.updated_by, updated_at = excluded.updated_at""",
            (extra.scope, extra.key, extra.name, extra.prompt, extra.point, extra.effect, extra.model,
             1 if extra.enabled else 0, extra.updated_by, extra.updated_at.isoformat()),
        )
        await self._db.commit()

    async def delete_extra(self, scope: str, key: str) -> None:
        await self._db.execute("DELETE FROM team_extras WHERE scope = ? AND key = ?", (scope, key))
        await self._db.commit()

    async def replace_extras(self, scope: str, extras: list[Extra]) -> None:
        await self._db.execute("DELETE FROM team_extras WHERE scope = ?", (scope,))
        await self._db.commit()
        for extra in extras:
            await self.save_extra(extra)

    # ── teams an agent proposes (v046) ──
    async def add_proposal(self, scope: str, body: str, why: str, by: str, at: str) -> int:
        cursor = await self._db.execute(
            "INSERT INTO team_proposals (scope, body, why, proposed_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (scope, body, why, by, at),
        )
        await self._db.commit()
        return int(cursor.lastrowid or 0)

    async def proposals(self, *, status: str = "open", scope: str | None = None, limit: int = 20) -> list[dict]:
        sql, args = "SELECT * FROM team_proposals WHERE status = ?", [status]
        if scope is not None:
            sql, args = sql + " AND scope = ?", [*args, scope]
        cursor = await self._db.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
        return [dict(row) for row in await cursor.fetchall()]

    async def proposal(self, proposal_id: int) -> dict | None:
        cursor = await self._db.execute("SELECT * FROM team_proposals WHERE id = ?", (proposal_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def decide_proposal(self, proposal_id: int, status: str, by: str, at: str) -> None:
        await self._db.execute(
            "UPDATE team_proposals SET status = ?, decided_by = ?, decided_at = ? WHERE id = ? AND status = 'open'",
            (status, by, at, proposal_id),
        )
        await self._db.commit()
