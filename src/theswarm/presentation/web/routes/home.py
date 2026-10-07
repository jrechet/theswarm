"""The home (M6, from the V2 module): Now, Ops, Requests, To review, the
projects — the owner's front door; a member's `/` is their customer."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from theswarm.presentation.web.routes import common
from theswarm.presentation.web.routes.common import _clock, _demo_card, _running_repos_safe, _when

router = APIRouter(tags=["home"])

log = logging.getLogger(__name__)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """The picker: repositories the owner confided to the GitHub App."""
    state = request.app.state
    from theswarm.presentation.web.routes.customers import member_home

    sent_home = await member_home(request)  # a member's home is their customer (V3 M2)
    if sent_home is not None:
        return sent_home
    creds = await common.github_app.load_credentials()

    repos: list[dict] = []
    seen: set[str] = set()
    if creds is not None:
        try:
            for r in await common.github_app.list_installation_repositories():
                full_name = r.get("full_name", "")
                owner, _, name = full_name.partition("/")
                repos.append({
                    "full_name": full_name, "owner": owner, "name": name,
                    "description": r.get("description") or "",
                    "private": bool(r.get("private")),
                    "language": r.get("language") or "",
                    "pushed_at": r.get("pushed_at") or "",
                })
                seen.add(full_name)
        except Exception:  # noqa: BLE001 — GitHub down ≠ no home page
            log.exception("Listing installation repositories failed")

    # "Tous mes projets": everything the owner's token can see, App or not.
    try:
        for r in await common.github_app.list_user_repositories():
            full_name = r.get("full_name", "")
            if not full_name or full_name in seen:
                continue
            owner, _, name = full_name.partition("/")
            repos.append({
                "full_name": full_name, "owner": owner, "name": name,
                "description": r.get("description") or "",
                "private": bool(r.get("private")),
                "language": r.get("language") or "",
                "pushed_at": r.get("pushed_at") or "",
            })
            seen.add(full_name)
    except Exception:  # noqa: BLE001
        log.exception("Listing the owner's repositories failed")

    # Registered projects that predate the App (or exist without it) stay
    # reachable — the flip to V2 must not orphan them.
    for project in await state.list_projects_query.execute():
        full_name = project.repo
        if full_name in seen or "/" not in full_name:
            continue
        owner, _, name = full_name.partition("/")
        repos.append({
            "full_name": full_name, "owner": owner, "name": name,
            "description": "", "private": False, "language": "",
            "pushed_at": "",
        })
    repos.sort(key=lambda r: r["pushed_at"], reverse=True)

    install_url = ""
    if creds is not None and creds.html_url:
        install_url = f"{creds.html_url}/installations/new"

    running = _running_repos_safe()
    return state.templates.TemplateResponse("home.html", {
        "repos": repos,
        "app_configured": creds is not None,
        "install_url": install_url,
        "oauth_ready": (await common.github_app.oauth_client()) is not None,
        "now": _now_cards(state, running),
        "running_repos": set(running),
        "to_review": await _recent_demos(state),
        "requests": await _requests_waiting(state),
        "ops": await _ops_card(state),
        "proposals": await _proposals(state),
        "today": datetime.now(timezone.utc).strftime("%A %d %B, %H:%M UTC").replace(" 0", " "),
    })


def _now_cards(state, running: dict[str, object]) -> list[dict]:
    """The queued and running cycles for the home's Now section."""
    base = state.base_path
    cards = []
    for repo, record in running.items():
        title = (record.description or "").strip()
        if not title:
            title = f"issue #{record.issue_number}" if record.issue_number else "the daily cycle"
        if len(title) > 90:
            title = title[:89].rstrip() + "…"
        cards.append({
            "id": record.id, "repo": repo, "issue_number": record.issue_number,
            "title": title, "status": record.status.value,
            "since": _clock(record.started_at or record.created_at),
            "sort": record.created_at,
            "href": f"{base}/cycles/{record.id}",
        })
    cards.sort(key=lambda c: c["sort"], reverse=True)
    return cards


async def _proposals(state) -> dict:
    """What DevOps proposes (D3): waiting for the owner, and what was decided lately."""
    service = getattr(state, "proposal_service", None)
    if service is None:
        return {"open": [], "recent": []}
    try:
        open_ = [p for p in await service.open() if p.status == "proposed"]
        recent = [p for p in await service.recent(limit=6) if p.status != "proposed"]
    except Exception:  # noqa: BLE001 — the page stays
        log.exception("home: reading the proposals failed")
        return {"open": [], "recent": []}
    return {"open": open_, "recent": recent}


async def _ops_card(state) -> dict | None:
    """The DevOps card (D1): the last report, never a wait for ssh or GitHub."""
    watch = getattr(state, "ops_watch", None)
    if watch is None:
        return None
    report = watch.last()
    if report is None:
        return {"status": "unknown", "stack": "", "read_at": "", "rows": [], "pending": True, "error": watch.error}
    return {
        "status": report.status, "stack": report.stack,
        "read_at": report.read_at.astimezone(timezone.utc).strftime("%H:%M UTC"),
        "rows": [f.as_dict() for f in report.findings], "pending": False, "error": watch.error,
        "counts": report.counts,
    }


async def _requests_waiting(state, limit: int = 5) -> list[dict]:
    """The requests waiting for the owner (V3 M5), for the home."""
    service = getattr(state, "request_service", None)
    if service is None:
        return []
    from theswarm.presentation.web.routes.requests_routes import inbox_rows

    try:
        return await inbox_rows(state, limit=limit)
    except Exception:  # noqa: BLE001 — the page stays, the section is empty
        log.exception("V2: reading the requests failed")
        return []


async def _recent_demos(state, limit: int = 5) -> list[dict]:
    """The latest demos across every project, for the home's To review."""
    report_repo = getattr(state, "report_repo", None)
    if report_repo is None:
        return []
    try:
        reports = await report_repo.list_recent(limit=limit)
    except Exception:  # noqa: BLE001 — the page stays, the section is empty
        log.exception("V2: reading recent demo reports failed")
        return []
    rows = []
    for report in reports:
        card = _demo_card(state, report)
        gates = list(report.quality_gates)
        failed = [g for g in gates if str(getattr(g.status, "value", g.status)) == "fail"]
        card.update({
            "repo": report.project_id,
            "when": _when(report.created_at),
            "gates_total": len(gates),
            "gates_label": ("Gates pass" if not failed
                            else f"{len(failed)} gate{'s' if len(failed) != 1 else ''} failed"),
            "gates_kind": "ok" if not failed else "bad",
        })
        rows.append(card)
    return rows
