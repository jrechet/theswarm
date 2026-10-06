"""The V3 shell — what every page's rail and top bar know.

docs/plans/2026-10-v3-one-product.md, M1. One rail on every screen: home,
the customers and their projects (one customer, Internal, until M2), the
project the page is about, Claude's health, who is signed in. The pages
never pass it: `ShellMiddleware` builds it once per HTML request and the
template engine hands it to every template as ``shell``.

The data must never cost a page its answer — a database or tracker
failure leaves an empty rail, logged, and the page renders.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from theswarm.presentation.web import auth

log = logging.getLogger(__name__)

_current: ContextVar[dict | None] = ContextVar("theswarm_shell", default=None)

CUSTOMER_INTERNAL = {"name": "Internal", "slug": "internal", "initial": "I"}


def empty_shell(path: str = "") -> dict:
    return {
        "actor": None,
        "customers": [],
        "claude": {"status": "unknown", "label": "Claude", "detail": ""},
        "active": "",
        "path": path,
    }


def current_shell() -> dict:
    """The shell of the request being rendered (empty outside one)."""
    return _current.get() or empty_shell()


# ── Pieces ───────────────────────────────────────────────────────────


def actor_from_headers(headers: dict[str, str]) -> dict | None:
    """Who the request is: the session's subject (owner or member), or the key."""
    subject = auth.session_login(headers)
    if subject:
        kind, ident = auth.subject_parts(subject)
        if kind == "member":
            return {"kind": "member", "member_id": ident, "login": "", "role": "member"}
        return {"kind": "owner", "login": ident, "role": "owner"}
    if auth.bearer_is_access_key(headers):
        return {"kind": "key", "login": "access key", "role": "owner"}
    return None


def claude_status() -> dict:
    """Claude's health as /health reports it: ok, a quota wall, dead credentials."""
    from theswarm.tools import auth_wall, quota_wall

    wall = quota_wall.wall_until()
    if wall is not None:
        until = wall.astimezone(timezone.utc).strftime("%H:%M UTC") if isinstance(wall, datetime) else str(wall)
        return {"status": "quota_wall", "label": "Claude: quota wall", "detail": f"until {until}"}
    if auth_wall.wall_until() is not None:
        return {"status": "auth_expired", "label": "Claude: credentials expired", "detail": ""}
    return {"status": "ok", "label": "Claude ok", "detail": ""}


def running_repos() -> dict[str, object]:
    """Repository → its queued or running cycle record, from the tracker."""
    from theswarm.api import CycleStatus, get_cycle_tracker

    found: dict[str, object] = {}
    for record in get_cycle_tracker().list_recent(limit=50):
        if record.status in (CycleStatus.QUEUED, CycleStatus.RUNNING):
            found.setdefault(record.repo, record)
    return found


def active_for(path: str, base: str, projects: list[str], running: dict[str, object]) -> str:
    """What the rail highlights: 'home', a project's full name, or nothing."""
    rel = path[len(base):] if base and path.startswith(base) else path
    if rel in ("", "/"):
        return "home"
    if rel.startswith("/r/"):
        for full_name in projects:
            if rel == f"/r/{full_name}" or rel.startswith(f"/r/{full_name}/"):
                return full_name
    if rel.startswith("/c/"):
        cycle_id = rel[3:].split("/", 1)[0]
        for full_name, record in running.items():
            if getattr(record, "id", "") == cycle_id:
                return full_name
    return ""


async def build_shell(state, headers: dict[str, str], path: str, base: str) -> dict:
    shell = empty_shell(path)
    service = getattr(state, "customer_service", None)

    # Who: a member's session is only worth its active row (V3 M2).
    actor = actor_from_headers(headers)
    member_customer = ""
    if actor is not None and actor["kind"] == "member":
        real = None
        if service is not None:
            try:
                real = await service.actor_for_member(actor["member_id"])
            except Exception:  # noqa: BLE001
                log.exception("shell: reading the member failed")
        if real is None:
            actor = None
        else:
            member_customer = real.customer_id
            actor = {"kind": "member", "member_id": real.member_id, "login": real.login,
                     "role": "", "customer_id": real.customer_id}
    shell["actor"] = actor
    shell["is_member"] = bool(member_customer)

    try:
        shell["claude"] = claude_status()
    except Exception:  # noqa: BLE001 — never a page's problem
        log.exception("shell: Claude status failed")

    # The projects, grouped by customer (Internal alone when nothing is wired).
    projects: list = []
    query = getattr(state, "list_projects_query", None)
    if query is not None:
        try:
            projects = [p for p in await query.execute() if "/" in str(p.repo)]
        except Exception:  # noqa: BLE001
            log.exception("shell: listing projects failed")
    customers: list = []
    if service is not None:
        try:
            customers = await service.list_all()
        except Exception:  # noqa: BLE001
            log.exception("shell: listing customers failed")
    running: dict[str, object] = {}
    try:
        running = running_repos()
    except Exception:  # noqa: BLE001
        log.exception("shell: reading the cycle tracker failed")

    def project_row(p) -> dict:
        full_name = str(p.repo)
        return {
            "name": p.repo.name, "full_name": full_name,
            "href": f"{base}/r/{full_name}", "running": full_name in running,
        }

    groups: list[dict] = []
    if customers:
        for c in customers:
            if member_customer and c.id != member_customer:
                continue
            rows = sorted((project_row(p) for p in projects if getattr(p, "customer_id", "internal") == c.id),
                          key=lambda r: r["full_name"])
            if member_customer:
                for row in rows:
                    row["href"] = f"{base}/c/{c.slug}"  # a member's projects have no page of their own yet (M5)
            if rows or c.id != "internal":
                groups.append({"name": c.name, "slug": c.slug, "initial": c.initial,
                               "href": f"{base}/c/{c.slug}", "projects": rows})
        if member_customer and groups:
            shell["actor"]["role"] = groups[0]["name"]
            shell["customer"] = groups[0]
    elif projects:
        groups.append({**CUSTOMER_INTERNAL, "href": f"{base}/",
                       "projects": sorted((project_row(p) for p in projects), key=lambda r: r["full_name"])})
    shell["customers"] = groups

    full_names = [str(p.repo) for p in projects]
    active = active_for(path, base, full_names, running)
    rel = path[len(base):] if base and path.startswith(base) else path
    if not active:
        if rel.startswith("/settings"):
            active = "settings"
        elif rel.startswith("/c/"):
            slug = rel[3:].split("/", 1)[0].rstrip("/")
            if any(g["slug"] == slug for g in groups):
                active = f"customer:{slug}"
    shell["active"] = active
    return shell


# ── The middleware ───────────────────────────────────────────────────


def _wants_html(headers: dict[str, str]) -> bool:
    return "text/html" in headers.get("accept", "")


class ShellMiddleware:
    """Builds the shell for every HTML GET and hands it to the templates."""

    SKIP_PREFIXES = ("/static/", "/api/", "/health", "/webhooks/", "/artifacts/")

    def __init__(self, app, base_path: str = "") -> None:
        self.app = app
        self.base = base_path.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method", "GET") not in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        headers = auth._headers(scope)
        path = scope.get("path", "")
        rel = path[len(self.base):] if self.base and path.startswith(self.base) else path
        if not _wants_html(headers) or rel.startswith(self.SKIP_PREFIXES):
            return await self.app(scope, receive, send)

        state = getattr(scope.get("app"), "state", None)
        try:
            shell = await build_shell(state, headers, path, self.base)
        except Exception:  # noqa: BLE001 — the page answers whatever the rail knows
            log.exception("shell: building the rail failed")
            shell = empty_shell(path)
        token = _current.set(shell)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
