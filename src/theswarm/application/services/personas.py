"""The team of a project: each role's persona, resolved (phase B, B1).

A project's persona inherits from the instance's, the instance's from the
built-in role; the model and effort also fall back on Settings → Agents'
choice (`agent_settings`, the instance-wide table B1 keeps underneath).
A cycle reads its team when it starts (`for_cycle`): a change applies to the
next cycle, never to one already running.
"""

from __future__ import annotations

import logging
from typing import Any

from theswarm.domain.agents.persona import INSTANCE, Persona, TeamMember
from theswarm.domain.agents.roles import ROLES

log = logging.getLogger(__name__)

_WORDS = ("name", "description", "instructions")


class PersonaService:
    def __init__(self, repo: Any, agent_settings: Any = None) -> None:
        self._repo = repo
        self._agent_settings = agent_settings
        self._rows: dict[tuple[str, str], Persona] = {}

    async def refresh(self) -> None:
        try:
            self._rows = {(p.scope, p.key): p for p in await self._repo.list_all()}
        except Exception:  # noqa: BLE001 — the last read stands
            log.exception("Personas: reading them failed")

    def stored(self, scope: str, key: str) -> Persona | None:
        return self._rows.get((scope, key))

    def team(self, project: str = INSTANCE) -> dict[str, TeamMember]:
        """Every role as `project` meets it, off the last read (never waits)."""
        models = self._agent_settings.snapshot() if self._agent_settings is not None else {}
        team: dict[str, TeamMember] = {}
        for role in ROLES:
            mine = self._rows.get((project, role.key)) if project else None
            instance = self._rows.get((INSTANCE, role.key))
            values: dict[str, str] = {"name": role.name, "description": "", "instructions": "", "model": "", "effort": ""}
            sources: dict[str, str] = {field: "built-in" for field in values}
            setting = models.get(role.key)
            if setting is not None:
                values["model"], values["effort"] = setting.model, setting.effort
                sources["model"] = sources["effort"] = "instance"
            for source, row in (("instance", instance), ("project", mine)):
                if row is None:
                    continue
                for field in _WORDS:
                    if getattr(row, field):
                        values[field], sources[field] = getattr(row, field), source
                if row.model:  # a model brings its effort with it ("" is Claude Code's own)
                    values["model"], values["effort"] = row.model, row.effort
                    sources["model"] = sources["effort"] = source
            team[role.key] = TeamMember(key=role.key, sources=sources, **values)
        return team

    async def for_cycle(self, project: str) -> tuple[dict[str, tuple[str, str]], dict[str, dict[str, str]]]:
        """(each role's (model, effort) where one is chosen, each role's words
        where the owner wrote some) for a cycle starting on `project`."""
        await self.refresh()
        if self._agent_settings is not None:
            await self._agent_settings.refresh()
        team = self.team(project)
        models = {key: (m.model, m.effort) for key, m in team.items() if m.model}
        words = {
            key: {"name": m.name, "description": m.description, "instructions": m.instructions}
            for key, m in team.items()
            if m.description or m.instructions or m.sources.get("name") != "built-in"
        }
        return models, words

    async def save(self, scope: str, key: str, *, name: str = "", description: str = "", instructions: str = "",
                   model: str = "", effort: str = "", by: str = "owner") -> Persona | None:
        """Write one persona; all empty is no row (it inherits everything)."""
        persona = Persona(scope=scope, key=key, name=name.strip(), description=" ".join(description.split()),
                          instructions=instructions.strip(), model=model, effort=effort if model else "", updated_by=by)
        if persona.empty:
            await self._repo.delete(scope, key)
            persona = None
        else:
            await self._repo.save(persona)
        await self.refresh()
        await self._record_version(scope, by)
        return persona

    # ── B2: the team as a file, its versions, the one a cycle started with ──

    def _of(self, scope: str) -> list[Persona]:
        return [p for (s, _), p in sorted(self._rows.items()) if s == scope]

    def export_yaml(self, scope: str = INSTANCE) -> str:
        from theswarm.application.services import team_yaml

        return team_yaml.dump(scope, self._of(scope))

    async def import_yaml(self, scope: str, text: str, *, by: str = "owner") -> int:
        """Replace `scope`'s personas with the file's, all validated first.
        Returns the new version (the current one when nothing changed)."""
        from theswarm.application.services import team_yaml

        personas = team_yaml.load(text, scope, by=by)
        await self._repo.replace_scope(scope, personas)
        await self.refresh()
        return await self._record_version(scope, by)

    async def _record_version(self, scope: str, by: str) -> int:
        """A new numbered version of `scope` when its file changed."""
        body = self.export_yaml(scope)
        try:
            last = await self._repo.versions(scope, limit=1)
            if last and last[0]["body"] == body:
                return int(last[0]["version"])
            from datetime import datetime, timezone

            return await self._repo.add_version(scope, body, by, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        except Exception:  # noqa: BLE001 — the personas are saved; only the history line is missing
            log.exception("Personas: the version of %r could not be recorded", scope or "instance")
            return 0

    async def versions(self, scope: str = INSTANCE, limit: int = 20) -> list[dict]:
        try:
            return await self._repo.versions(scope, limit)
        except Exception:  # noqa: BLE001
            log.exception("Personas: reading the versions of %r failed", scope or "instance")
            return []

    async def for_thread(self, thread_id: str, project: str) -> tuple[dict[str, tuple[str, str]], dict[str, dict[str, str]], str]:
        """The team of the cycle running on graph thread `thread_id`: the one
        it started with when it has one (a continuation after a deploy or a
        pause), else today's, pinned now. Returns (models, words, label)."""
        import json
        from datetime import datetime, timezone

        try:
            kept = await self._repo.pinned(thread_id)
        except Exception:  # noqa: BLE001
            kept = None
        if kept is not None:
            team = json.loads(kept["team"])
            return ({k: tuple(v) for k, v in team.get("models", {}).items()}, team.get("words", {}), kept["label"])
        models, words = await self.for_cycle(project)
        try:
            latest = await self._repo.latest_versions()
            label = f"{project} v{latest.get(project, 0)} · instance v{latest.get(INSTANCE, 0)}"
            await self._repo.pin(thread_id, project, label, json.dumps({"models": models, "words": words}),
                                 datetime.now(timezone.utc).isoformat(timespec="seconds"))
        except Exception:  # noqa: BLE001 — the cycle runs on today's team; only the pin is missing
            log.exception("Personas: the team of thread %s could not be pinned", thread_id)
            label = ""
        return models, words, label
