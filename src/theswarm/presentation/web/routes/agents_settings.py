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


def _flows(service, scope: str) -> list[dict]:
    """B4: each flow drawn — its steps, and in each slot the free personas
    placed there. The ones written for this scope can be moved; the ones a
    project inherits from every project are shown where they are."""
    from theswarm.domain.teams.templates import DRAWINGS, TEMPLATES

    team = service.team(scope)
    own = {e.key for e in service.extras_of(scope)}
    met = service.extras_for(scope) + [e for e in service.extras_of(scope) if not e.enabled]
    flows = []
    for flow in TEMPLATES:
        steps = []
        for kind, key, label in DRAWINGS[flow.key]:
            step = {"kind": kind, "key": key, "label": label}
            if kind == "role":
                step["who"] = team[key].name
            if kind == "slot":
                step["chips"] = [{"key": e.key, "name": e.name, "effect": e.effect, "movable": e.key in own,
                                  "enabled": e.enabled} for e in sorted(met, key=lambda e: e.key) if e.point == key]
            steps.append(step)
        flows.append({"key": flow.key, "name": flow.name, "what": flow.what, "steps": steps})
    return flows


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
    from theswarm.domain.teams.extras import EFFECTS, MAX_PER_TEAM, POINTS, PROMPT_MAX

    stored = service.extras_of(scope) if service is not None else []
    inherited = [e for e in (service.extras_of("") if service is not None and scope else [])
                 if e.key not in {x.key for x in stored}]
    extras_context = {
        "extras": [{"key": e.key, "name": e.name, "prompt": e.prompt, "point": e.point, "effect": e.effect,
                    "model": e.model, "enabled": e.enabled} for e in stored],
        "extras_inherited": [{"name": e.name, "point": dict(POINTS).get(e.point, e.point), "enabled": e.enabled}
                             for e in inherited],
        "extra_points": POINTS, "extra_effects": EFFECTS, "extras_max": MAX_PER_TEAM, "prompt_max": PROMPT_MAX,
        "extras_full": len(stored) >= MAX_PER_TEAM,
    }
    extras_context["flows"] = _flows(service, scope) if service is not None else []
    versions = await service.versions(scope, limit=5) if service is not None else []
    proposals = await service.open_proposals(scope) if service is not None else []
    extras_context["team_proposals"] = [
        {"id": p["id"], "why": p["why"], "by": p["proposed_by"], "at": str(p["created_at"])[:16].replace("T", " "),
         "body": p["body"]} for p in proposals]
    return {**extras_context, "team_yaml": service.export_yaml(scope) if service is not None else "",
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


@router.post("/settings/agents/extra")
async def save_extra(request: Request):
    """B3: add, change or remove a free persona of a team (the instance's or one project's)."""
    from urllib.parse import quote

    from theswarm.domain.teams.extras import ExtraError
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
    if scope and scope not in await _projects(state):
        return await _render(request, error="That project is not on this page.", status_code=400)
    try:
        if form.get("remove"):
            await service.delete_extra(scope, key, by=actor.login)
        else:
            await service.save_extra(
                scope, key=key, name=str(form.get("name") or ""), prompt=str(form.get("prompt") or ""),
                point=str(form.get("point") or ""), effect=str(form.get("effect") or "comment"),
                model=str(form.get("model") or ""), enabled=form.get("enabled") is not None or not key, by=actor.login,
            )
    except ExtraError as exc:
        return await _render(request, error=str(exc), status_code=400)
    log.info("Free persona %s of %s %s by %s", key or form.get("name"), scope or "the instance",
             "removed" if form.get("remove") else "saved", actor.login)
    where = f"team={quote(scope, safe='')}&" if scope else ""
    return RedirectResponse(f"{state.base_path}/settings/agents?{where}team_saved=extra#extras", status_code=303)


@router.post("/settings/agents/proposals/{proposal_id}/{decision}")
async def decide_proposal(request: Request, proposal_id: int, decision: str):
    """B5: the owner accepts (the file is imported) or refuses a team an agent proposed."""
    from urllib.parse import quote

    from theswarm.application.services.team_yaml import TeamYamlError
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    actor = await _owner(request)
    if actor is None:
        return _refused(request, await current_actor(request))
    service = getattr(state, "personas", None)
    if service is None or decision not in ("accept", "refuse"):
        return await _render(request, error="That is not a decision this page takes.", status_code=400)
    try:
        decided = await service.decide(proposal_id, accept=decision == "accept", by=actor.login)
    except TeamYamlError as exc:  # valid when proposed, not any more (a role renamed since)
        return await _render(request, error=f"The proposal could not be applied: {exc}", status_code=400)
    if decided is None:
        return await _render(request, error="That proposal is not waiting any more.", status_code=409)
    log.info("Team proposal %s %s by %s", proposal_id, decided["status"], actor.login)
    where = f"team={quote(decided['scope'], safe='')}&" if decided["scope"] else ""
    saved = "import" if decision == "accept" else "refused"
    return RedirectResponse(f"{state.base_path}/settings/agents?{where}team_saved={saved}#team", status_code=303)


@router.post("/settings/agents/extra/move")
async def move_extra(request: Request):
    """B4: a free persona dropped on another insertion point of the flow. Only
    a point is a target, so no drop draws a flow that does not ship; an effect
    the new point does not take becomes a comment."""
    from fastapi.responses import JSONResponse

    from theswarm.domain.teams.extras import COMMENT, EFFECTS_AT, ExtraError
    from theswarm.presentation.web.routes.customers import current_actor

    state = request.app.state
    actor = await _owner(request)
    service = getattr(state, "personas", None)
    if actor is None or service is None:
        refused = await current_actor(request)
        return JSONResponse({"moved": False, "why": "The owner moves the team's personas."},
                            status_code=403 if refused is None or not refused.is_owner else 503)
    form = await request.form()
    scope, key, point = str(form.get("team") or ""), str(form.get("key") or ""), str(form.get("point") or "")
    extra = next((e for e in service.extras_of(scope) if e.key == key), None)
    if extra is None or point not in EFFECTS_AT:
        return JSONResponse({"moved": False, "why": "That persona or that point is not of this team."}, status_code=400)
    effect = extra.effect if extra.effect in EFFECTS_AT[point] else COMMENT
    try:
        await service.save_extra(scope, key=key, name=extra.name, prompt=extra.prompt, point=point, effect=effect,
                                 model=extra.model, enabled=extra.enabled, by=actor.login)
    except ExtraError as exc:
        return JSONResponse({"moved": False, "why": str(exc)}, status_code=400)
    log.info("Free persona %s of %s moved to %s by %s", key, scope or "the instance", point, actor.login)
    return JSONResponse({"moved": True, "point": point, "effect": effect,
                         "note": "" if effect == extra.effect else "It comments there: nothing is left to block."})


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
