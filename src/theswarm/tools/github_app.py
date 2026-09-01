"""GitHub App identity: credentials, app JWT, installation tokens.

The App replaces the static ``GITHUB_TOKEN`` with short-lived installation
tokens (1 h, minted on demand, cached until 5 min before expiry). Credentials
live in the Fernet vault under the reserved project id ``__github_app__``;
env vars (``GITHUB_APP_ID`` + ``GITHUB_APP_PRIVATE_KEY`` + ...) are the
fallback for CLI/dev contexts without a vault.

``ensure_github_token()`` is the one integration point: it resolves the best
available token and exports it as ``GITHUB_TOKEN`` so the two existing
consumers (PyGitHub in tools/github.py, ``git -c http.extraheader`` in
tools/git.py) keep reading the env exactly as before. Without App
credentials it is a no-op and the static token keeps working — the
documented rollback path.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import httpx
import jwt

GITHUB_API = "https://api.github.com"
VAULT_PROJECT_ID = "__github_app__"
_VAULT_KEYS = (
    "app_id", "private_key_pem", "client_id", "client_secret",
    "webhook_secret", "slug", "html_url",
)

_JWT_LIFETIME_SECONDS = 540       # GitHub max is 600; leave clock-skew room
_JWT_SKEW_SECONDS = 60
_TOKEN_REFRESH_MARGIN_SECONDS = 300


@dataclass(frozen=True)
class GitHubAppCredentials:
    """Everything the manifest conversion returns that we need to keep."""

    app_id: str
    private_key_pem: str
    client_id: str
    client_secret: str
    webhook_secret: str = ""
    slug: str = ""
    html_url: str = ""


# Module state: one App per deployment, so a module singleton is honest.
_vault: object | None = None
_credentials: GitHubAppCredentials | None = None
_credentials_loaded = False
_token: str = ""
_token_expires_at: float = 0.0
_lock: asyncio.Lock | None = None


def reset_state() -> None:
    """Tests only — forget cached credentials and tokens."""
    global _vault, _credentials, _credentials_loaded, _token, _token_expires_at
    _vault = None
    _credentials = None
    _credentials_loaded = False
    _token = ""
    _token_expires_at = 0.0


def configure(vault: object) -> None:
    """Remember the vault; credentials load lazily on first use."""
    global _vault, _credentials_loaded
    _vault = vault
    _credentials_loaded = False


def _env_credentials() -> GitHubAppCredentials | None:
    app_id = os.environ.get("GITHUB_APP_ID", "").strip()
    key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").strip()
    if not app_id or not key:
        return None
    return GitHubAppCredentials(
        app_id=app_id,
        private_key_pem=key,
        client_id=os.environ.get("GITHUB_APP_CLIENT_ID", "").strip(),
        client_secret=os.environ.get("GITHUB_APP_CLIENT_SECRET", "").strip(),
    )


async def store_credentials(creds: GitHubAppCredentials) -> None:
    """Persist to the vault and make them current immediately."""
    global _credentials, _credentials_loaded, _token, _token_expires_at
    if _vault is None:
        raise RuntimeError("github_app.configure(vault) was never called")
    values = {
        "app_id": creds.app_id,
        "private_key_pem": creds.private_key_pem,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "webhook_secret": creds.webhook_secret,
        "slug": creds.slug,
        "html_url": creds.html_url,
    }
    for key, value in values.items():
        await _vault.set(VAULT_PROJECT_ID, key, value)
    _credentials = creds
    _credentials_loaded = True
    _token, _token_expires_at = "", 0.0


async def load_credentials() -> GitHubAppCredentials | None:
    """Vault first, env fallback; result cached until reconfigured."""
    global _credentials, _credentials_loaded
    if _credentials_loaded:
        return _credentials
    creds: GitHubAppCredentials | None = None
    if _vault is not None:
        try:
            values = {
                k: (await _vault.get(VAULT_PROJECT_ID, k)) or ""
                for k in _VAULT_KEYS
            }
            if values["app_id"] and values["private_key_pem"]:
                creds = GitHubAppCredentials(**values)
        except Exception:  # vault locked/misconfigured → fall back to env
            creds = None
    if creds is None:
        creds = _env_credentials()
    _credentials = creds
    _credentials_loaded = True
    return creds


def app_jwt(creds: GitHubAppCredentials, now: float | None = None) -> str:
    """Short-lived RS256 JWT that authenticates *as the App itself*."""
    issued = int(now if now is not None else time.time())
    payload = {
        "iat": issued - _JWT_SKEW_SECONDS,
        "exp": issued + _JWT_LIFETIME_SECONDS,
        "iss": creds.app_id,
    }
    return jwt.encode(payload, creds.private_key_pem, algorithm="RS256")


async def installation_token(force: bool = False) -> str | None:
    """Cached installation token, refreshed 5 min before expiry.

    Single-tenant: the App is expected to have exactly one installation
    (the owner's); the first one wins.
    """
    global _token, _token_expires_at, _lock
    creds = await load_credentials()
    if creds is None:
        return None
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if (
            not force and _token
            and time.time() < _token_expires_at - _TOKEN_REFRESH_MARGIN_SECONDS
        ):
            return _token
        headers = {
            "Authorization": f"Bearer {app_jwt(creds)}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{GITHUB_API}/app/installations", headers=headers,
            )
            resp.raise_for_status()
            installations = resp.json()
            if not installations:
                return None
            installation_id = installations[0]["id"]
            resp = await client.post(
                f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        _token = data["token"]
        # expires_at: "2026-09-01T13:00:00Z" — parse without a new dep
        from datetime import datetime, timezone
        expires = datetime.fromisoformat(
            data["expires_at"].replace("Z", "+00:00"),
        )
        _token_expires_at = expires.replace(tzinfo=timezone.utc).timestamp() \
            if expires.tzinfo is None else expires.timestamp()
        return _token


async def ensure_github_token() -> str:
    """Resolve the freshest token and export it as ``GITHUB_TOKEN``.

    The export keeps every existing consumer working unchanged; a static
    ``GITHUB_TOKEN`` without App credentials passes straight through.
    """
    token = await installation_token()
    if token:
        os.environ["GITHUB_TOKEN"] = token
        return token
    return os.environ.get("GITHUB_TOKEN", "")


async def list_installation_repositories() -> list[dict]:
    """Repos the owner confided to the App — the V2 picker's data source."""
    token = await installation_token()
    if not token:
        return []
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    repos: list[dict] = []
    url = f"{GITHUB_API}/installation/repositories?per_page=100"
    async with httpx.AsyncClient(timeout=20) as client:
        while url:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            repos.extend(payload.get("repositories", []))
            url = resp.links.get("next", {}).get("url", "")
    return repos
