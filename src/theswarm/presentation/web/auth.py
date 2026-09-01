"""Session auth for the dashboard — closed by default (issue #38).

Design:
- Signed, HttpOnly session cookie (HMAC-SHA256, stdlib only).
- Pure-ASGI middleware so SSE streaming is never buffered.
- Fail-safe: the wall is up unless ``SWARM_AUTH_DISABLED`` is truthy —
  losing an env var locks the app, it never silently opens it (the #31
  lesson, inverted).
- Two doors: the access key (``SWARM_ACCESS_KEY``) now; GitHub OAuth joins
  it once the GitHub App exists. Both mint the same session.
- Ops scripting: ``Authorization: Bearer <access key>`` passes the wall for
  API calls without a cookie dance.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import quote, urlparse

from fastapi.responses import JSONResponse, RedirectResponse

SESSION_COOKIE = "swarm_session"
SESSION_TTL_SECONDS = 14 * 24 * 3600

# Paths that stay open, and why (prefix match on "/"-terminated entries):
#   /health*   — Docker healthcheck kills the container without it
#   /static/   — css/js/fonts needed by the login page itself
#   /login     — the door
#   /auth/     — OAuth dance (étape 1)
#   /webhooks/ — GitHub webhook authenticates with its own HMAC signature
#   /d/        — deliberately public demo short-links
_PUBLIC_EXACT = frozenset({"/health", "/login"})
_PUBLIC_PREFIXES = ("/health/", "/static/", "/auth/", "/webhooks/", "/d/")

_LOGIN_MAX_FAILURES = 5
_LOGIN_LOCKOUT_SECONDS = 60

_ephemeral_secret: str | None = None
_login_failures: dict[str, tuple[int, float]] = {}


def _session_secret() -> str:
    """Env secret, or a process-ephemeral one (sessions die on restart)."""
    configured = os.environ.get("SWARM_SESSION_SECRET", "").strip()
    if configured:
        return configured
    global _ephemeral_secret
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(32)
    return _ephemeral_secret


def auth_disabled() -> bool:
    return os.environ.get("SWARM_AUTH_DISABLED", "").strip().lower() in (
        "1", "true", "yes",
    )


def access_key() -> str:
    return os.environ.get("SWARM_ACCESS_KEY", "").strip()


# ── Session tokens ─────────────────────────────────────────────────────


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def mint_session(
    login: str, *, secret: str | None = None,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> str:
    secret = secret or _session_secret()
    expires = int(time.time()) + ttl_seconds
    encoded = base64.urlsafe_b64encode(login.encode()).decode().rstrip("=")
    payload = f"{encoded}.{expires}"
    return f"{payload}.{_sign(payload, secret)}"


def verify_session(token: str, *, secret: str | None = None) -> str | None:
    secret = secret or _session_secret()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    encoded, expires_raw, signature = parts
    payload = f"{encoded}.{expires_raw}"
    if not hmac.compare_digest(_sign(payload, secret), signature):
        return None
    try:
        if int(expires_raw) < time.time():
            return None
        padding = "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(encoded + padding).decode()
    except (ValueError, UnicodeDecodeError):
        return None


# ── Login throttle (in-memory, per process) ────────────────────────────


def reset_login_throttle() -> None:
    _login_failures.clear()


def login_locked(client_ip: str) -> bool:
    failures, locked_until = _login_failures.get(client_ip, (0, 0.0))
    return failures >= _LOGIN_MAX_FAILURES and time.time() < locked_until


def record_login_failure(client_ip: str) -> None:
    failures, _ = _login_failures.get(client_ip, (0, 0.0))
    _login_failures[client_ip] = (
        failures + 1, time.time() + _LOGIN_LOCKOUT_SECONDS,
    )


def record_login_success(client_ip: str) -> None:
    _login_failures.pop(client_ip, None)


# ── Request helpers ────────────────────────────────────────────────────


def _headers(scope: dict) -> dict[str, str]:
    return {
        k.decode("latin-1").lower(): v.decode("latin-1")
        for k, v in scope.get("headers", [])
    }


def client_ip(scope_or_headers: dict, fallback: str = "?") -> str:
    headers = (
        _headers(scope_or_headers)
        if "headers" in scope_or_headers and isinstance(
            scope_or_headers.get("headers"), (list, tuple),
        )
        else scope_or_headers
    )
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return fallback


def _cookie_value(headers: dict[str, str]) -> str:
    raw = headers.get("cookie", "")
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE:
            return value
    return ""


def _is_public(path: str) -> bool:
    return path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIXES)


def _same_origin(headers: dict[str, str]) -> bool:
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site in ("same-origin", "none")
    origin = headers.get("origin")
    if not origin:
        return True  # non-browser client; the session/bearer check decides
    host = headers.get("x-forwarded-host") or headers.get("host", "")
    return urlparse(origin).netloc == host.split(",")[0].strip()


# ── The wall ───────────────────────────────────────────────────────────


class AuthWallMiddleware:
    """Pure-ASGI gate: session cookie or Bearer access key, else 401/303."""

    def __init__(self, app, base_path: str = "") -> None:
        self.app = app
        self.base = base_path.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or auth_disabled():
            return await self.app(scope, receive, send)

        path = scope["path"]
        headers = _headers(scope)
        method = scope.get("method", "GET")

        if _is_public(path):
            return await self.app(scope, receive, send)

        # CSRF: refuse cross-site writes even with a valid session.
        if method not in ("GET", "HEAD", "OPTIONS") and not _same_origin(headers):
            response = JSONResponse(
                {"detail": "Cross-site request refused"}, status_code=403,
            )
            return await response(scope, receive, send)

        if self._is_authenticated(headers):
            return await self.app(scope, receive, send)

        login_url = f"{self.base}/login"
        if headers.get("hx-request") == "true":
            response = JSONResponse(
                {"detail": "Session expired"}, status_code=401,
                headers={"HX-Redirect": login_url},
            )
        elif method == "GET" and "text/html" in headers.get("accept", ""):
            query = scope.get("query_string", b"").decode()
            # The app sees proxy-stripped paths, the browser does not:
            # next must carry the public prefix or the post-login redirect
            # lands outside the app (bots.jrec.fr/projects/ → 404).
            target = f"{self.base}{path}" + (f"?{query}" if query else "")
            response = RedirectResponse(
                f"{login_url}?next={quote(target, safe='')}", status_code=303,
            )
        else:
            response = JSONResponse(
                {"detail": "Authentication required"}, status_code=401,
            )
        await response(scope, receive, send)

    def _is_authenticated(self, headers: dict[str, str]) -> bool:
        token = _cookie_value(headers)
        if token and verify_session(token) is not None:
            return True
        bearer = headers.get("authorization", "")
        key = access_key()
        if key and bearer.startswith("Bearer "):
            return hmac.compare_digest(bearer.removeprefix("Bearer "), key)
        return False
