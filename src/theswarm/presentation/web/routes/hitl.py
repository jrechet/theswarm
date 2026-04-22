"""Human-in-the-loop audit + cycle nudge routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()


def _audit_repo(request: Request):
    repo = getattr(request.app.state, "hitl_audit_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="hitl audit not configured")
    return repo


# ── Nudge: add a human note to a running cycle ──────────────────────


@router.post("/cycles/{cycle_id}/nudge")
async def cycle_nudge(
    request: Request,
    cycle_id: str,
    note: str = Form(...),
    project_id: str = Form(""),
) -> JSONResponse:
    repo = _audit_repo(request)
    audit_id = await repo.record(
        project_id=project_id,
        cycle_id=cycle_id,
        action="nudge",
        target=cycle_id,
        note=note,
    )
    # Best-effort: push into the cycle repository's checkpoint notes if available.
    return JSONResponse({"audit_id": audit_id, "ok": True})


# ── Explicit intervention endpoints ─────────────────────────────────


@router.post("/cycles/{cycle_id}/pause")
async def cycle_pause(
    request: Request,
    cycle_id: str,
    project_id: str = Form(""),
    note: str = Form(""),
) -> JSONResponse:
    repo = _audit_repo(request)
    audit_id = await repo.record(
        project_id=project_id,
        cycle_id=cycle_id,
        action="pause",
        target=cycle_id,
        note=note,
    )
    return JSONResponse({"audit_id": audit_id, "ok": True})


@router.post("/cycles/{cycle_id}/intervene")
async def cycle_intervene(
    request: Request,
    cycle_id: str,
    action: str = Form(...),
    project_id: str = Form(""),
    target: str = Form(""),
    note: str = Form(""),
) -> JSONResponse:
    repo = _audit_repo(request)
    allowed = {"skip", "override", "resume", "ask-answered"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"action must be one of {sorted(allowed)}")
    audit_id = await repo.record(
        project_id=project_id,
        cycle_id=cycle_id,
        action=action,
        target=target or cycle_id,
        note=note,
    )
    return JSONResponse({"audit_id": audit_id, "ok": True})


# ── Audit viewer ────────────────────────────────────────────────────


@router.get("/hitl", response_class=HTMLResponse)
async def hitl_index(request: Request) -> HTMLResponse:
    repo = getattr(request.app.state, "hitl_audit_repo", None)
    entries = await repo.list_recent(limit=200) if repo is not None else []
    return request.app.state.templates.TemplateResponse(
        "hitl_audit.html",
        {"request": request, "entries": entries, "scope": "all"},
    )


@router.get("/projects/{project_id}/hitl", response_class=HTMLResponse)
async def hitl_project(request: Request, project_id: str) -> HTMLResponse:
    repo = getattr(request.app.state, "hitl_audit_repo", None)
    entries = (
        await repo.list_for_project(project_id, limit=200)
        if repo is not None
        else []
    )
    return request.app.state.templates.TemplateResponse(
        "hitl_audit.html",
        {"request": request, "entries": entries, "scope": project_id},
    )
