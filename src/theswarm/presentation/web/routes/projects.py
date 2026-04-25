"""Project CRUD routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from theswarm.application.commands.create_project import (
    CreateProjectCommand,
    CreateProjectHandler,
)
from theswarm.application.commands.delete_project import (
    DeleteProjectCommand,
    DeleteProjectHandler,
)
from theswarm.application.commands.update_project_config import (
    ProjectNotFound,
    UpdateProjectConfigCommand,
    UpdateProjectConfigHandler,
)
from theswarm.application.queries.get_project import GetProjectQuery
from theswarm.application.queries.list_projects import ListProjectsQuery

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects")


@router.get("/", response_class=HTMLResponse)
async def list_projects(request: Request) -> HTMLResponse:
    query: ListProjectsQuery = request.app.state.list_projects_query
    projects = await query.execute()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects_list.html",
        {"request": request, "projects": projects},
    )


@router.get("/new", response_class=HTMLResponse)
async def create_form(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects_create.html",
        {"request": request},
    )


@router.post("/", response_class=RedirectResponse)
async def create_project(
    request: Request,
    project_id: str = Form(...),
    repo: str = Form(...),
    framework: str = Form("auto"),
    ticket_source: str = Form("github"),
    team_channel: str = Form(""),
) -> RedirectResponse:
    handler: CreateProjectHandler = request.app.state.create_project_handler
    await handler.handle(
        CreateProjectCommand(
            project_id=project_id,
            repo=repo,
            framework=framework,
            ticket_source=ticket_source,
            team_channel=team_channel,
        )
    )
    base = request.app.state.base_path
    return RedirectResponse(url=f"{base}/projects/", status_code=303)


@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str) -> HTMLResponse:
    query: GetProjectQuery = request.app.state.get_project_query
    project = await query.execute(project_id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    templates = request.app.state.templates
    secret_keys: list[str] = []
    vault = getattr(request.app.state, "secret_vault", None)
    if vault is not None:
        try:
            secret_keys = await vault.list_keys(project_id)
        except Exception:
            log.exception("Failed to list secret keys for project %s", project_id)
    return templates.TemplateResponse(
        "projects_detail.html",
        {"request": request, "project": project, "secret_keys": secret_keys},
    )


@router.post("/{project_id}/delete", response_class=RedirectResponse)
async def delete_project(request: Request, project_id: str) -> RedirectResponse:
    handler: DeleteProjectHandler = request.app.state.delete_project_handler
    await handler.handle(DeleteProjectCommand(project_id=project_id))
    base = request.app.state.base_path
    return RedirectResponse(url=f"{base}/projects/", status_code=303)


# ── C1 / C2 — config editor (HTMX PATCH + JSON fallback) ──────────────


def _parse_models_field(raw: str) -> dict[str, str]:
    """Accept '' (no change) or comma-separated 'phase=model' pairs."""
    out: dict[str, str] = {}
    if not raw.strip():
        return out
    for part in raw.split(","):
        if "=" not in part:
            raise ValueError(f"models entry must be 'phase=model', got {part!r}")
        phase, model = part.split("=", 1)
        phase = phase.strip()
        model = model.strip()
        if not phase or not model:
            raise ValueError(f"empty phase or model in {part!r}")
        out[phase] = model
    return out


@router.patch("/{project_id}/config")
async def patch_project_config(request: Request, project_id: str) -> JSONResponse:
    """PATCH project config — accepts JSON or form-encoded body."""
    handler: UpdateProjectConfigHandler | None = getattr(
        request.app.state, "update_project_config_handler", None,
    )
    if handler is None:
        raise HTTPException(status_code=501, detail="config editor not configured")

    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        if not isinstance(data, dict):
            raise HTTPException(status_code=422, detail="body must be a JSON object")
    else:
        form = await request.form()
        data = {k: v for k, v in form.items()}
        if "models" in data and isinstance(data["models"], str):
            try:
                data["models"] = _parse_models_field(data["models"])
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

    def _maybe(name: str, cast):
        v = data.get(name)
        if v is None or v == "":
            return None
        try:
            return cast(v)
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"{name}: {e}")

    cmd = UpdateProjectConfigCommand(
        project_id=project_id,
        effort=_maybe("effort", str),
        models=data.get("models") if isinstance(data.get("models"), dict) else None,
        max_daily_stories=_maybe("max_daily_stories", int),
        daily_cost_cap_usd=_maybe("daily_cost_cap_usd", float),
        daily_tokens_cap=_maybe("daily_tokens_cap", int),
        monthly_cost_cap_usd=_maybe("monthly_cost_cap_usd", float),
        paused=_maybe("paused", lambda v: str(v).lower() in ("1", "true", "yes", "on")),
        token_budget_po=_maybe("token_budget_po", int),
        token_budget_techlead=_maybe("token_budget_techlead", int),
        token_budget_dev=_maybe("token_budget_dev", int),
        token_budget_qa=_maybe("token_budget_qa", int),
    )
    try:
        new_config = await handler.handle(cmd)
    except ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return JSONResponse({
        "project_id": project_id,
        "effort": new_config.effort,
        "models": dict(new_config.models),
        "max_daily_stories": new_config.max_daily_stories,
        "daily_cost_cap_usd": new_config.daily_cost_cap_usd,
        "daily_tokens_cap": new_config.daily_tokens_cap,
        "monthly_cost_cap_usd": new_config.monthly_cost_cap_usd,
        "paused": new_config.paused,
    })


# ── C6 — pause / resume ──────────────────────────────────────────────


async def _audit(request: Request, project_id: str, action: str, actor: str = "") -> None:
    db = getattr(request.app.state, "db", None)
    if db is None:
        return
    try:
        await db.execute(
            """INSERT INTO project_audit (project_id, action, actor, detail, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, action, actor, "", datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
    except Exception:
        log.exception("audit log insert failed")


async def _set_paused(request: Request, project_id: str, paused: bool) -> dict:
    handler: UpdateProjectConfigHandler | None = getattr(
        request.app.state, "update_project_config_handler", None,
    )
    if handler is None:
        raise HTTPException(status_code=501, detail="config editor not configured")
    try:
        cfg = await handler.handle(
            UpdateProjectConfigCommand(project_id=project_id, paused=paused),
        )
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail="project not found")
    actor = request.headers.get("x-actor", "")
    await _audit(request, project_id, "pause" if paused else "resume", actor)
    return {"project_id": project_id, "paused": cfg.paused}


@router.post("/{project_id}/pause")
async def pause_project(request: Request, project_id: str) -> JSONResponse:
    return JSONResponse(await _set_paused(request, project_id, True))


@router.post("/{project_id}/resume")
async def resume_project(request: Request, project_id: str) -> JSONResponse:
    return JSONResponse(await _set_paused(request, project_id, False))


# ── C3 — secret vault write-only UI ───────────────────────────────────


@router.post("/{project_id}/secrets")
async def set_secret(
    request: Request,
    project_id: str,
    key_name: str = Form(...),
    value: str = Form(...),
) -> JSONResponse:
    vault = getattr(request.app.state, "secret_vault", None)
    if vault is None:
        raise HTTPException(status_code=501, detail="vault not configured")
    if not key_name.strip() or not value:
        raise HTTPException(status_code=422, detail="key_name and value required")
    try:
        await vault.set(project_id, key_name.strip(), value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        log.exception("vault set failed")
        raise HTTPException(status_code=500, detail=f"vault error: {e}")
    return JSONResponse({"project_id": project_id, "key_name": key_name.strip()})


@router.delete("/{project_id}/secrets/{key_name}", status_code=204)
async def delete_secret(request: Request, project_id: str, key_name: str):
    from fastapi import Response
    vault = getattr(request.app.state, "secret_vault", None)
    if vault is None:
        raise HTTPException(status_code=501, detail="vault not configured")
    await vault.delete(project_id, key_name)
    return Response(status_code=204)


@router.get("/{project_id}/memory", response_class=HTMLResponse)
async def project_memory_viewer(
    request: Request,
    project_id: str,
    category: str = "",
    agent: str = "",
) -> HTMLResponse:
    """Sprint E M1 — project memory viewer with client-side search."""
    project_repo = request.app.state.project_repo
    project = await project_repo.get(project_id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    templates = request.app.state.templates
    query = getattr(request.app.state, "list_project_memory_query", None)
    entries: list = []
    if query is not None:
        entries = await query.execute(project_id, category=category, agent=agent)
    categories = [
        "stack", "conventions", "errors",
        "architecture", "improvements", "cross_project",
    ]
    return templates.TemplateResponse(
        "projects_memory.html",
        {
            "request": request,
            "project": project,
            "entries": entries,
            "categories": categories,
            "category": category,
            "agent": agent,
        },
    )


@router.get("/{project_id}/cost-estimate")
async def project_cost_estimate(request: Request, project_id: str) -> JSONResponse:
    """Sprint D C5 — tokens + USD estimate for the next cycle.

    Also returns the backlog preview — what PO will pick up — so the
    Run Cycle modal can answer "what am I about to run?".
    """
    project_repo = request.app.state.project_repo
    project = await project_repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    estimator = getattr(request.app.state, "cost_estimator", None)
    if estimator is None:
        from theswarm.application.services.cost_estimator import CostEstimator
        estimator = CostEstimator(request.app.state.cycle_repo)
    estimate = await estimator.estimate(project)

    # Backlog preview — call the project's ticket source for status:backlog issues
    backlog: list[dict] = []
    backlog_error: str | None = None
    try:
        from theswarm.tools.github import GitHubClient
        gh = GitHubClient(repo_name=str(project.repo))
        issues = await gh.get_issues(labels=["status:backlog"], state="open")
        for issue in issues[:5]:
            backlog.append({
                "number": getattr(issue, "number", None),
                "title": getattr(issue, "title", "") or "",
                "url": getattr(issue, "html_url", "") or "",
            })
    except Exception as exc:
        backlog_error = f"{type(exc).__name__}: {exc}"

    return JSONResponse({
        "tokens": estimate.tokens,
        "cost_usd": estimate.cost_usd,
        "basis": estimate.basis,
        "sample_size": estimate.sample_size,
        "models_by_phase": estimate.models_by_phase,
        "backlog": backlog,
        "backlog_error": backlog_error,
        "max_dev_iterations": getattr(getattr(project, "config", None), "max_daily_stories", None) or getattr(project, "max_daily_stories", 5),
        "repo": str(project.repo),
    })
