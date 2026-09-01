"""Login and logout — the only doors through the auth wall.

Two doors mint the same session: the access key (break-glass, always
available) and GitHub OAuth via the GitHub App (owner-only allowlist,
``SWARM_OWNER_LOGIN``). ``/auth/*`` is in the wall's public list so the
OAuth dance can happen while logged out.
"""

from __future__ import annotations

import hmac
import logging
import os
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.presentation.web import auth
from theswarm.tools import github_app

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

_OAUTH_STATE_TTL_SECONDS = 600


def owner_login() -> str:
    return os.environ.get("SWARM_OWNER_LOGIN", "jrechet").strip()


def _safe_next(raw: str, base: str) -> str:
    """Only app-relative paths — never an absolute URL (open redirect)."""
    if raw.startswith("/") and not raw.startswith("//"):
        return raw
    return f"{base}/" if base else "/"


def _set_session_cookie(response: RedirectResponse, request: Request) -> None:
    base = request.app.state.base_path
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.mint_session("owner"),
        max_age=auth.SESSION_TTL_SECONDS,
        path=f"{base}/" if base else "/",
        httponly=True,
        samesite="lax",
        secure=forwarded_proto == "https",
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "") -> HTMLResponse:
    templates = request.app.state.templates
    creds = await github_app.load_credentials()
    return templates.TemplateResponse("login.html", {
        "next": next,
        "error": request.query_params.get("error", ""),
        "github_login": creds is not None and bool(creds.client_id),
    })


@router.post("/login")
async def login_submit(
    request: Request,
    access_key: str = Form(default=""),
    next: str = Form(default=""),
):
    templates = request.app.state.templates
    base = request.app.state.base_path
    ip = auth.client_ip(dict(request.headers), fallback=request.client.host if request.client else "?")

    if auth.login_locked(ip):
        return templates.TemplateResponse(
            "login.html",
            {"next": next, "error": "Too many attempts — wait a minute."},
            status_code=429,
        )

    expected = auth.access_key()
    if not expected or not hmac.compare_digest(access_key, expected):
        auth.record_login_failure(ip)
        return templates.TemplateResponse(
            "login.html",
            {"next": next, "error": "That key doesn't match."},
            status_code=401,
        )

    auth.record_login_success(ip)
    response = RedirectResponse(_safe_next(next, base), status_code=303)
    _set_session_cookie(response, request)
    return response


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    base = request.app.state.base_path
    response = RedirectResponse(f"{base}/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE, path=f"{base}/" if base else "/")
    return response


# ── GitHub OAuth (via the GitHub App's client id/secret) ───────────────


@router.get("/auth/github")
async def github_oauth_start(request: Request):
    base = request.app.state.base_path
    creds = await github_app.load_credentials()
    if creds is None or not creds.client_id:
        return RedirectResponse(
            f"{base}/login?error=GitHub+login+is+not+configured+yet",
            status_code=303,
        )
    from theswarm.presentation.web.routes.github_setup import external_base
    state = auth.mint_session(
        "oauth-state", ttl_seconds=_OAUTH_STATE_TTL_SECONDS,
    )
    params = urlencode({
        "client_id": creds.client_id,
        "redirect_uri": f"{external_base(request)}/auth/github/callback",
        "state": state,
    })
    return RedirectResponse(
        f"https://github.com/login/oauth/authorize?{params}", status_code=303,
    )


@router.get("/auth/github/callback")
async def github_oauth_callback(
    request: Request, code: str = "", state: str = "",
):
    base = request.app.state.base_path
    if auth.verify_session(state) != "oauth-state":
        return RedirectResponse(
            f"{base}/login?error=Sign-in+expired+—+try+again", status_code=303,
        )
    creds = await github_app.load_credentials()
    if creds is None or not code:
        return RedirectResponse(f"{base}/login", status_code=303)

    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        access_token = token_resp.json().get("access_token", "")
        if not access_token:
            log.warning("OAuth exchange failed: %s", token_resp.text[:200])
            return RedirectResponse(
                f"{base}/login?error=GitHub+refused+the+sign-in+code",
                status_code=303,
            )
        user_resp = await client.get(
            f"{github_app.GITHUB_API}/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    login = user_resp.json().get("login", "")

    if login.lower() != owner_login().lower():
        log.warning("OAuth sign-in refused for GitHub user %r", login)
        return RedirectResponse(
            f"{base}/login?error=This+instance+belongs+to+someone+else",
            status_code=303,
        )

    response = RedirectResponse(f"{base}/" if base else "/", status_code=303)
    _set_session_cookie(response, request)
    return response
