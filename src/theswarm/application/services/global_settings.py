"""Dashboard-managed global settings.

Stores keys that the platform needs (Anthropic API key, GitHub token, public
URLs, …) in the same encrypted vault used for per-project secrets, but under
the reserved namespace ``_global``. On boot, we copy any stored values into
``os.environ`` if they are not already set there, so existing code paths
(ClaudeCLI, GitHubClient, etc.) keep working without modification.

When a value is updated through the dashboard, ``set`` patches ``os.environ``
immediately so the change takes effect without a restart.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from theswarm.infrastructure.persistence.secret_vault import SqliteSecretVault, VaultError

log = logging.getLogger(__name__)

GLOBAL_NAMESPACE = "_global"


@dataclass(frozen=True)
class SettingDef:
    key: str            # env var name (e.g. ANTHROPIC_API_KEY)
    label: str          # human label
    description: str    # short help text
    secret: bool = True # mask value in UI
    required: bool = False


SETTINGS_SCHEMA: tuple[SettingDef, ...] = (
    SettingDef(
        "ANTHROPIC_API_KEY",
        "Anthropic API key",
        "Required for sprint composer, agents, NLU. Get one at console.anthropic.com.",
        secret=True, required=True,
    ),
    SettingDef(
        "GITHUB_TOKEN",
        "GitHub token",
        "Personal access token with `repo` scope. Used to read backlog and create PRs.",
        secret=True, required=True,
    ),
    SettingDef(
        "SWARM_GITHUB_REPO",
        "Default GitHub repo",
        "Fallback repo when a cycle has no project context. Format: owner/repo.",
        secret=False,
    ),
    SettingDef(
        "EXTERNAL_URL",
        "Public dashboard URL",
        "Used for Mattermost callbacks and webhook addresses. e.g. https://bots.example.com/swarm",
        secret=False,
    ),
    SettingDef(
        "MATTERMOST_BOT_TOKEN",
        "Mattermost bot token",
        "Optional. Token for the @swarm-po bot.",
        secret=True,
    ),
    SettingDef(
        "SEQ_URL",
        "Seq logging URL",
        "Optional. Enables structured log shipping to Seq.",
        secret=False,
    ),
    SettingDef(
        "SEQ_API_KEY",
        "Seq API key",
        "Optional. Auth token for Seq.",
        secret=True,
    ),
)


class GlobalSettings:
    """Read/write the ``_global`` vault namespace and mirror to ``os.environ``."""

    def __init__(self, vault: SqliteSecretVault) -> None:
        self._vault = vault

    async def all(self) -> dict[str, str | None]:
        """Return {key: stored_value_or_None} for every entry in SETTINGS_SCHEMA.

        Stored values come from the vault; environment-only values are returned
        as None so the UI can flag them as "set via env, not editable here".
        """
        out: dict[str, str | None] = {}
        for s in SETTINGS_SCHEMA:
            try:
                out[s.key] = await self._vault.get(GLOBAL_NAMESPACE, s.key)
            except VaultError:
                out[s.key] = None
        return out

    async def set(self, key: str, value: str) -> None:
        if not any(s.key == key for s in SETTINGS_SCHEMA):
            raise ValueError(f"unknown setting: {key}")
        value = value.strip()
        if value:
            await self._vault.set(GLOBAL_NAMESPACE, key, value)
            os.environ[key] = value
        else:
            await self._vault.delete(GLOBAL_NAMESPACE, key)
            os.environ.pop(key, None)

    async def apply_to_env(self) -> int:
        """Copy stored values into os.environ if not already set. Returns count applied."""
        applied = 0
        for s in SETTINGS_SCHEMA:
            if os.environ.get(s.key):
                continue
            try:
                v = await self._vault.get(GLOBAL_NAMESPACE, s.key)
            except VaultError as exc:
                log.warning("global settings: cannot read %s: %s", s.key, exc)
                continue
            if v:
                os.environ[s.key] = v
                applied += 1
        return applied
