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
        **await _team_context(request),
        "rows": _rows(settings), "models": MODELS, "efforts": EFFORTS, "available": service is not None,
        "instance_model": _MODEL_LABELS.get(default, default), "saved": request.query_params.get("saved") == "1",
        "error": error,
    }, status_code=status_code)


async def _projects(state) -> list[str]:
    repo = getattr(state, "project_repo", None)
    if repo is None:
        return []
    try:
        return sorted({str(p.repo) for p in await repo.list_all() if "/" in str(p.repo)})
    except Exception:  # noqa: BLE001 — the page without its projects
        log.exception("settings/agents: listing the projects failed")
        return []


async def _team_context(request: Request) -> dict:
    """Phase B, B1 — who each role is, for the instance or the project the
    page is on (`?team=owner/name`): the stored words, and what an empty
    field inherits."""
    from theswarm.domain.agents.persona import DESCRIPTION_MAX, INSTRUCTIONS_MAX, NAME_MAX
    from theswarm.domain.agents.roles import CYCLE_ROLES

    state = request.app.state
    service = getattr(state, "personas", None)
    projects = await _projects(state)
    scope = request.query_params.get("team", "")
    if scope not in projects:
        scope = ""
    members = []
    if service is not None:
        await service.refresh()
        inherited = service.team("")  # what a project's empty field falls back on
        resolved = service.team(scope)
        # The four roles of the cycle: their prompts open with these words
        # (`base.load_context`). DevOps's calls do not, so it is not offered.
        for role in CYCLE_ROLES:
            row = service.stored(scope, role.key)
            base = inherited[role.key]
            members.append({
                "key": role.key, "role": role.name,
                "name": row.name if row else "", "description": row.description if row else "",
                "instructions": row.instructions if row else "",
                "model": row.model if row else "", "effort": row.effort if row else "",
                "inherits_name": base.name if scope else role.name,
                "inherits_description": base.description if scope else "",
                "inherits_instructions": bool(base.instructions) if scope else False,
                "resolved_name": resolved[role.key].name,
                "set": row is not None,
                "updated": f"{row.updated_at:%d %b %H:%M UTC} by {row.updated_by}".lstrip("0") if row and row.updated_by else "",
            })
    versions = await service.versions(scope, limit=5) if service is not None else []
    return {"team_yaml": service.export_yaml(scope) if service is not None else "",
            "team_versions": [{"version": v["version"], "by": v["created_by"],
                               "at": str(v["created_at"])[:16].replace("T", " ")} for v in versions],
            "team_available": service is not None, "team_scope": scope, "team_projects": projects,
            "team_members": members, "name_max": NAME_MAX, "description_max": DESCRIPTION_MAX,
            "instructions_max": INSTRUCTIONS_MAX, "team_saved": request.query_params.get("team_saved", "")}


@router.post("/settings/agents/persona")
async def save_persona(request: Request):
    """One role's persona, for the instance or one project. Everything left
    empty is no row: the role inherits."""
    from theswarm.domain.agents.persona import PersonaError
    from theswarm.domain.agents.roles import CYCLE_ROLE_KEYS as ROLE_KEYS
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    actor = await _owner(request)
    if actor is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "personas", None)
    if service is None:
        return await _render(request, error="Personas need the database.", status_code=503)
    form = await request.form()
    scope, key = str(form.get("team") or ""), str(form.get("key") or "")
    if key not in ROLE_KEYS or (scope and scope not in await _projects(state)):
        return await _render(request, error="That role or that project is not on this page.", status_code=400)
    try:
        await service.save(
            scope, key, name=str(form.get("name") or ""), description=str(form.get("description") or ""),
            instructions=str(form.get("instructions") or ""),
            model=str(form.get("model") or "") if scope else "", effort=str(form.get("effort") or "") if scope else "",
            by=actor.login,
        )
    except PersonaError as exc:
        return await _render(request, error=str(exc), status_code=400)
    log.info("Persona %s saved for %s by %s", key, scope or "the instance", actor.login)
    from urllib.parse import quote

    where = f"team={quote(scope, safe='')}&" if scope else ""
    return RedirectResponse(f"{state.base_path}/settings/agents?{where}team_saved={key}#team", status_code=303)


@router.get("/settings/agents/team.yaml")
async def team_file(request: Request):
    """B2: the team of the instance or of one project (`?team=owner/name`) as YAML."""
    from fastapi.responses import PlainTextResponse

    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    if await _owner(request) is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "personas", None)
    scope = request.query_params.get("team", "")
    if service is None or (scope and scope not in await _projects(state)):
        return PlainTextResponse("No such team.\n", status_code=404)
    await service.refresh()
    return PlainTextResponse(service.export_yaml(scope), media_type="text/yaml; charset=utf-8")


@router.post("/settings/agents/team/import")
async def import_team(request: Request):
    """B2: replace a team's personas with a YAML file's — validated whole, or nothing changes."""
    from urllib.parse import quote

    from theswarm.application.services.team_yaml import TeamYamlError
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    actor = await _owner(request)
    if actor is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "personas", None)
    if service is None:
        return await _render(request, error="Personas need the database.", status_code=503)
    form = await request.form()
    scope = str(form.get("team") or "")
    if scope and scope not in await _projects(state):
        return await _render(request, error="That project is not on this page.", status_code=400)
    try:
        version = await service.import_yaml(scope, str(form.get("yaml") or ""), by=actor.login)
    except TeamYamlError as exc:
        return await _render(request, error=f"The team file was not imported: {exc}", status_code=400)
    log.info("Team of %s imported by %s (version %s)", scope or "the instance", actor.login, version)
    where = f"team={quote(scope, safe='')}&" if scope else ""
    return RedirectResponse(f"{state.base_path}/settings/agents?{where}team_saved=import#team", status_code=303)


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
