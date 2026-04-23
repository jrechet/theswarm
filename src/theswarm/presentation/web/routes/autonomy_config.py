"""Autonomy-spectrum config routes (Phase L).

Per-project panel — one row per role with a level selector.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.autonomy_config.value_objects import AutonomyLevel
from theswarm.presentation.web.fragment_response import render_fragment_or_page

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _service(request: Request):
    svc = getattr(request.app.state, "autonomy_config_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503, detail="autonomy config service not configured",
        )
    return svc


async def _render(request: Request, project_id: str) -> HTMLResponse:
    svc = _service(request)
    configs = await svc.list_for_project(project_id)
    return render_fragment_or_page(
        request,
        "autonomy_config_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "configs": configs,
            "levels": list(AutonomyLevel),
        },
        page_title=f"Autonomy — {project_id}",
    )


@router.get(
    "/projects/{project_id}/autonomy",
    response_class=HTMLResponse,
)
async def autonomy_list(
    request: Request, project_id: str,
) -> HTMLResponse:
    return await _render(request, project_id)


@router.post(
    "/projects/{project_id}/autonomy",
    response_class=HTMLResponse,
)
async def autonomy_set(
    request: Request, project_id: str,
    role: str = Form(...),
    level: str = Form(...),
    note: str = Form(""),
    actor: str = Form(""),
) -> HTMLResponse:
    svc = _service(request)
    try:
        lvl = AutonomyLevel(level)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"invalid autonomy level: {level}",
        )
    await svc.set_level(
        project_id=project_id, role=role, level=lvl,
        note=note, actor=actor,
    )
    return await _render(request, project_id)
