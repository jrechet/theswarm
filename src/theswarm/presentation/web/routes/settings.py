"""Dashboard-managed global settings (API keys, URLs, tokens)."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.services.global_settings import (
    GLOBAL_NAMESPACE,
    SETTINGS_SCHEMA,
    GlobalSettings,
)
from theswarm.infrastructure.persistence.secret_vault import VaultError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "…" + value[-4:]


def _settings_service(request: Request) -> GlobalSettings | None:
    vault = getattr(request.app.state, "secret_vault", None)
    if vault is None:
        return None
    return GlobalSettings(vault)


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    svc = _settings_service(request)

    rows: list[dict] = []
    vault_ok = svc is not None
    vault_error: str | None = None

    stored: dict[str, str | None] = {}
    if svc is not None:
        try:
            stored = await svc.all()
        except VaultError as exc:
            vault_ok = False
            vault_error = str(exc)
        except Exception as exc:  # noqa: BLE001
            vault_ok = False
            vault_error = f"vault unavailable: {exc}"

    for s in SETTINGS_SCHEMA:
        env_value = os.environ.get(s.key, "")
        stored_value = stored.get(s.key) if vault_ok else None
        active = stored_value or env_value
        rows.append({
            "key": s.key,
            "label": s.label,
            "description": s.description,
            "secret": s.secret,
            "required": s.required,
            "is_set": bool(active),
            "masked": _mask(active) if s.secret else (active or ""),
            "from_env_only": bool(env_value and not stored_value),
        })

    return templates.render(
        "settings.html",
        request=request,
        rows=rows,
        vault_ok=vault_ok,
        vault_error=vault_error,
    )


@router.post("/{key}")
async def update_setting(request: Request, key: str, value: str = Form("")) -> RedirectResponse:
    svc = _settings_service(request)
    if svc is None:
        raise HTTPException(status_code=501, detail="vault not configured on this server")
    try:
        await svc.set(key, value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except VaultError as exc:
        raise HTTPException(status_code=503, detail=f"vault error: {exc}")
    base = request.app.state.base_path or ""
    return RedirectResponse(url=f"{base}/settings", status_code=303)
