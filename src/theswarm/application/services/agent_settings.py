"""Settings → Agents: the owner chooses each persona's Claude model and
effort; the cycle, the PO's customer summary and DevOps's improvements run on
it. A persona the owner did not set runs on the instance's model
(`SWARM_CLAUDE_MODEL`) with Claude Code's own effort — what every call did
before this existed.

`effective()` is read at the start of every cycle (a change applies to the
next one, never to one already running); `snapshot()` is the last read, for
the callers that cannot wait.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from theswarm.domain.agents.settings import PERSONA_KEYS, AgentSetting

log = logging.getLogger(__name__)


def instance_model() -> str:
    return os.environ.get("SWARM_CLAUDE_MODEL", "sonnet") or "sonnet"


class AgentSettingsService:
    def __init__(self, repo: Any) -> None:
        self._repo = repo
        self._snapshot: dict[str, AgentSetting] = {}

    async def refresh(self) -> dict[str, AgentSetting]:
        try:
            self._snapshot = await self._repo.list_all()
        except Exception:  # noqa: BLE001 — the last read stands, the instance's model otherwise
            log.exception("Agent settings: reading them failed")
        return dict(self._snapshot)

    def snapshot(self) -> dict[str, AgentSetting]:
        return dict(self._snapshot)

    async def effective(self) -> dict[str, tuple[str, str]]:
        """(model, effort) for each persona the owner set; the others run on the instance's model."""
        return {k: (s.model, s.effort) for k, s in (await self.refresh()).items()}

    async def save_all(self, choices: dict[str, tuple[str, str]], by: str = "owner") -> dict[str, AgentSetting]:
        """Each persona's (model, effort); a model of "" puts the persona back on the instance's model."""
        for persona in PERSONA_KEYS:
            if persona not in choices:
                continue
            model, effort = choices[persona]
            if not model:
                await self._repo.delete(persona)
                continue
            await self._repo.save(AgentSetting(persona=persona, model=model, effort=effort, updated_by=by))
        return await self.refresh()

    def claude_for(self, persona: str, base_model: str | None = None):
        """A Claude wrapper for a call outside the cycle (the customer summary, DevOps's improvement)."""
        from theswarm.tools.claude import ClaudeCLI

        setting = self._snapshot.get(persona)
        if setting is None:
            return ClaudeCLI(model=base_model or instance_model())
        return ClaudeCLI(model=setting.model, effort=setting.effort)
