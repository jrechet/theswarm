"""Login and logout — the only doors through the auth wall."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.presentation.web import auth

router = APIRouter(tags=["auth"])


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
    return templates.TemplateResponse("login.html", {"next": next, "error": ""})


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
