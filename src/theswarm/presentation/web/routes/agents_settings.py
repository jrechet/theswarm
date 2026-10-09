"""Settings → Agents: the owner chooses each persona's Claude model and effort.

The wall keeps `/settings/*` from a member; the routes check the owner too.
A change applies from the next cycle (a cycle reads the settings when it
starts), and at once to the PO's customer summaries and DevOps's
improvement pull requests.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.services.agent_settings import instance_model
from theswarm.domain.agents.settings import EFFORT_KEYS, EFFORTS, MODEL_KEYS, MODELS, PERSONAS, AgentSettingError

log = logging.getLogger(__name__)

router = APIRouter()

_MODEL_LABELS = dict(MODELS)
_EFFORT_LABELS = dict(EFFORTS)


async def _owner(request: Request):
    from theswarm.presentation.web.routes.customers import current_actor

    actor = await current_actor(request)
    return actor if actor is not None and actor.is_owner else None


def _rows(settings: dict) -> list[dict]:
    rows = []
    for key, name, what in PERSONAS:
        s = settings.get(key)
        rows.append({
            "key": key, "name": name, "what": what, "set": s is not None,
            "model": s.model if s else "", "effort": s.effort if s else "",
            "runs_on": (f"{_MODEL_LABELS.get(s.model, s.model)}"
                        + (f" · {_EFFORT_LABELS.get(s.effort, s.effort)} effort" if s.effort else " · Claude Code's effort"))
            if s else f"{_MODEL_LABELS.get(instance_model(), instance_model())} · Claude Code's effort (the instance's default)",
            "updated": f"{s.updated_at:%d %b %H:%M UTC} by {s.updated_by}".lstrip("0") if s and s.updated_by else "",
        })
    return rows


async def _render(request: Request, *, error: str = "", status_code: int = 200) -> HTMLResponse:
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    if await _owner(request) is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "agent_settings", None)
    settings = await service.refresh() if service is not None else {}
    default = instance_model()
    return state.templates.TemplateResponse("settings_agents.html", {
        "rows": _rows(settings), "models": MODELS, "efforts": EFFORTS, "available": service is not None,
        "instance_model": _MODEL_LABELS.get(default, default), "saved": request.query_params.get("saved") == "1",
        "error": error,
    }, status_code=status_code)


@router.get("/settings/agents", response_class=HTMLResponse)
async def agents_page(request: Request) -> HTMLResponse:
    return await _render(request)


@router.post("/settings/agents")
async def save_agents(request: Request):
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    actor = await _owner(request)
    if actor is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "agent_settings", None)
    if service is None:
        return await _render(request, error="Agent settings need the database.", status_code=503)
    form = await request.form()
    every_model, every_effort = str(form.get("all-model", "") or ""), str(form.get("all-effort", "") or "")
    choices: dict[str, tuple[str, str]] = {}
    for key, _, _ in PERSONAS:
        model = every_model if form.get("apply-all") else str(form.get(f"{key}-model", "") or "")
        effort = every_effort if form.get("apply-all") else str(form.get(f"{key}-effort", "") or "")
        if model and model not in MODEL_KEYS or effort and effort not in EFFORT_KEYS:
            return await _render(request, error=f"{key}: {model or '—'} · {effort or '—'} is not a choice on this page.", status_code=400)
        if effort and not model:
            model = instance_model() if instance_model() in MODEL_KEYS else "sonnet"  # an effort on the instance's model
        choices[key] = (model, effort)
    try:
        await service.save_all(choices, by=actor.login)
    except AgentSettingError as exc:
        return await _render(request, error=str(exc), status_code=400)
    log.info("Agent settings saved by %s: %s", actor.login, choices)
    return RedirectResponse(f"{state.base_path}/settings/agents?saved=1", status_code=303)
