"""Settings › Instance — the keys and URLs this instance runs on (V3, M6).

The vault-backed global settings V1's settings page wrote (ANTHROPIC_API_KEY,
GITHUB_TOKEN, SWARM_GITHUB_REPO, EXTERNAL_URL, MATTERMOST_BOT_TOKEN, SEQ_URL,
SEQ_API_KEY): shown masked, set or cleared one at a time, applied on the
next request and at boot. The owner's only (the wall admits no member here).
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.services.global_settings import SETTINGS_SCHEMA, GlobalSettings
from theswarm.infrastructure.persistence.secret_vault import VaultError

log = logging.getLogger(__name__)
router = APIRouter()

VAULT_HINT = (
    "Set SWARM_VAULT_MASTER_KEY on the server and redeploy; generate a key with "
    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
)


def mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "…" + value[-4:]


def _service(request: Request) -> GlobalSettings | None:
    vault = getattr(request.app.state, "secret_vault", None)
    return GlobalSettings(vault) if vault is not None else None


async def _rows(service: GlobalSettings | None) -> tuple[list[dict], bool, str]:
    """Every setting with where its value comes from; whether the vault answers."""
    stored: dict[str, str | None] = {}
    vault_ok = service is not None
    vault_error = "" if vault_ok else "No vault on this server. " + VAULT_HINT
    if service is not None:
        try:
            stored = await service.all()
        except VaultError as exc:
            vault_ok, vault_error = False, f"Vault error: {exc}"
        except Exception as exc:  # noqa: BLE001
            vault_ok, vault_error = False, f"Vault unavailable: {exc}"
    rows = []
    for s in SETTINGS_SCHEMA:
        env_value = os.environ.get(s.key, "")
        stored_value = stored.get(s.key) if vault_ok else None
        active = stored_value or env_value
        rows.append({
            "key": s.key, "label": s.label, "description": s.description, "secret": s.secret,
            "required": s.required, "is_set": bool(active),
            "shown": mask(active) if s.secret else (active or ""),
            "source": "vault" if stored_value else ("environment" if env_value else ""),
        })
    return rows, vault_ok, vault_error


async def _page(request: Request, error: str = "", status_code: int = 200) -> HTMLResponse:
    rows, vault_ok, vault_error = await _rows(_service(request))
    return request.app.state.templates.TemplateResponse("v3/settings_instance.html", {
        "rows": rows, "vault_ok": vault_ok, "vault_error": error or vault_error,
    }, status_code=status_code)


@router.get("/settings/instance", response_class=HTMLResponse)
async def instance_settings(request: Request) -> HTMLResponse:
    return await _page(request)


@router.post("/settings/instance/{key}")
async def update_instance_setting(request: Request, key: str, value: str = Form("")):
    """Set a value (empty clears it); a vault failure is said on the page, never a raw 503."""
    service = _service(request)
    if service is None:
        return await _page(request, error="No vault on this server. " + VAULT_HINT, status_code=503)
    try:
        await service.set(key, value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except VaultError as exc:
        return await _page(request, error=f"Vault error: {exc}", status_code=503)
    log.info("Instance setting %s %s", key, "cleared" if not value else "set")
    return RedirectResponse(f"{request.app.state.base_path}/settings/instance", status_code=303)
