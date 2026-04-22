"""Refactor programs dashboard routes (Phase L).

Portfolio-wide surface tracking coordinated multi-project refactors.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.refactor_programs.value_objects import (
    RefactorProgramStatus,
)

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _service(request: Request):
    svc = getattr(request.app.state, "refactor_program_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503, detail="refactor program service not configured",
        )
    return svc


def _parse_lines(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(
        ln for ln in (s.strip() for s in text.splitlines()) if ln
    )


@router.get("/refactor-programs", response_class=HTMLResponse)
async def programs_list(request: Request) -> HTMLResponse:
    svc = _service(request)
    programs = await svc.list()
    return _templates(request).TemplateResponse(
        "refactor_programs_fragment.html",
        {
            "request": request,
            "programs": programs,
            "statuses": list(RefactorProgramStatus),
        },
    )


@router.post("/refactor-programs", response_class=HTMLResponse)
async def programs_upsert(
    request: Request,
    title: str = Form(...),
    rationale: str = Form(""),
    target_projects: str = Form(""),
    owner: str = Form(""),
    status: str = Form("proposed"),
) -> HTMLResponse:
    svc = _service(request)
    try:
        status_enum = RefactorProgramStatus(status)
    except ValueError:
        status_enum = RefactorProgramStatus.PROPOSED
    await svc.upsert(
        title=title, rationale=rationale,
        target_projects=_parse_lines(target_projects),
        owner=owner, status=status_enum,
    )
    return await programs_list(request)


@router.post(
    "/refactor-programs/activate", response_class=HTMLResponse,
)
async def programs_activate(
    request: Request, title: str = Form(...),
) -> HTMLResponse:
    svc = _service(request)
    try:
        await svc.activate(title)
    except ValueError:
        raise HTTPException(
            status_code=404, detail="Refactor program not found",
        )
    return await programs_list(request)


@router.post(
    "/refactor-programs/complete", response_class=HTMLResponse,
)
async def programs_complete(
    request: Request, title: str = Form(...),
) -> HTMLResponse:
    svc = _service(request)
    try:
        await svc.complete(title)
    except ValueError:
        raise HTTPException(
            status_code=404, detail="Refactor program not found",
        )
    return await programs_list(request)


@router.post(
    "/refactor-programs/cancel", response_class=HTMLResponse,
)
async def programs_cancel(
    request: Request, title: str = Form(...),
) -> HTMLResponse:
    svc = _service(request)
    try:
        await svc.cancel(title)
    except ValueError:
        raise HTTPException(
            status_code=404, detail="Refactor program not found",
        )
    return await programs_list(request)


@router.post(
    "/refactor-programs/add-project", response_class=HTMLResponse,
)
async def programs_add_project(
    request: Request,
    title: str = Form(...),
    project_id: str = Form(...),
) -> HTMLResponse:
    svc = _service(request)
    try:
        await svc.add_project(title, project_id)
    except ValueError:
        raise HTTPException(
            status_code=404, detail="Refactor program not found",
        )
    return await programs_list(request)


@router.post(
    "/refactor-programs/remove-project", response_class=HTMLResponse,
)
async def programs_remove_project(
    request: Request,
    title: str = Form(...),
    project_id: str = Form(...),
) -> HTMLResponse:
    svc = _service(request)
    try:
        await svc.remove_project(title, project_id)
    except ValueError:
        raise HTTPException(
            status_code=404, detail="Refactor program not found",
        )
    return await programs_list(request)
