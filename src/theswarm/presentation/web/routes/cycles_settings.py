"""Settings → Cycles: how many cycles run at once, in all and per project.

The owner (2026-10-13): "le nombre de cycles max et par projet doivent être
configurables via l'interface". The wall keeps `/settings/*` from a member;
the routes check the owner too. A change applies at once: a cycle waiting
that now fits starts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.cycle_gate import (
    DEFAULT_REPO_MAX_CYCLES,
    MAX_IN_ALL,
    MAX_PER_REPO,
    env_max_concurrent_cycles,
    max_concurrent_cycles,
    repo_max_cycles,
)

log = logging.getLogger(__name__)

router = APIRouter()


async def _owner(request: Request):
    from theswarm.presentation.web.routes.customers import current_actor

    actor = await current_actor(request)
    return actor if actor is not None and actor.is_owner else None


async def _projects(state) -> list[str]:
    repo = getattr(state, "project_repo", None)
    if repo is None:
        return []
    try:
        return sorted({str(p.repo) for p in await repo.list_all() if "/" in str(p.repo)})
    except Exception:  # noqa: BLE001 — the page without its table
        log.exception("settings/cycles: listing the projects failed")
        return []


def _running_counts() -> dict[str, int]:
    try:
        from theswarm.presentation.web.shell import live_cycles

        counts: dict[str, int] = {}
        for record in live_cycles():
            if record.status.value == "running":
                counts[record.repo] = counts.get(record.repo, 0) + 1
        return counts
    except Exception:  # noqa: BLE001
        return {}


async def _render(request: Request, *, error: str = "", status_code: int = 200) -> HTMLResponse:
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    if await _owner(request) is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "cycle_limits", None)
    if service is not None:
        await service.refresh()
    running = _running_counts()
    rows = [{"repo": repo, "max": repo_max_cycles(repo), "running": running.get(repo, 0)}
            for repo in await _projects(state)]
    return state.templates.TemplateResponse("settings_cycles.html", {
        "available": service is not None, "in_all": max_concurrent_cycles(),
        "in_all_default": env_max_concurrent_cycles(), "in_all_set": bool(service and service.global_max()),
        "rows": rows, "max_in_all": MAX_IN_ALL, "max_per_repo": MAX_PER_REPO,
        "running_total": sum(running.values()),
        "saved": request.query_params.get("saved") == "1", "error": error,
    }, status_code=status_code)


@router.get("/settings/cycles", response_class=HTMLResponse)
async def cycles_page(request: Request) -> HTMLResponse:
    return await _render(request)


def _number(raw, default: int | None) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return default
    return int(text)


@router.post("/settings/cycles")
async def save_cycles(request: Request):
    from theswarm.application.services.cycle_limits import CycleLimitsError
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    actor = await _owner(request)
    if actor is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "cycle_limits", None)
    if service is None:
        return await _render(request, error="Cycle limits need the database.", status_code=503)
    form = await request.form()
    try:
        in_all = _number(form.get("in-all"), None)
        if in_all == env_max_concurrent_cycles():
            in_all = None  # the instance's default: no row
        per_repo = {repo: _number(form.get(f"repo:{repo}"), DEFAULT_REPO_MAX_CYCLES)
                    for repo in await _projects(state)}
        await service.save(in_all, per_repo, by=getattr(actor, "login", "") or "owner")
    except (CycleLimitsError, ValueError) as exc:
        return await _render(request, error=str(exc) or "A number, please.", status_code=400)
    log.info("Settings → Cycles: %s in all, %s per project", in_all or "default",
             {r: v for r, v in per_repo.items() if v != DEFAULT_REPO_MAX_CYCLES} or "1 each")
    return RedirectResponse(f"{state.base_path}/settings/cycles?saved=1", status_code=303)
