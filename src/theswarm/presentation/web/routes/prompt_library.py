"""Prompt library dashboard routes (Phase L)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.presentation.web.fragment_response import render_fragment_or_page

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _service(request: Request):
    svc = getattr(request.app.state, "prompt_library_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503, detail="prompt library service not configured",
        )
    return svc


async def _render_list(request: Request) -> HTMLResponse:
    svc = _service(request)
    templates = await svc.list()
    return render_fragment_or_page(
        request,
        "prompt_library_fragment.html",
        {"request": request, "templates": templates},
        page_title="Prompt Library",
    )


@router.get("/prompt-library", response_class=HTMLResponse)
async def library_list(request: Request) -> HTMLResponse:
    return await _render_list(request)


@router.post("/prompt-library", response_class=HTMLResponse)
async def library_upsert(
    request: Request,
    name: str = Form(...),
    body: str = Form(""),
    role: str = Form(""),
    actor: str = Form(""),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request)
    await svc.upsert(name=name, body=body, role=role, actor=actor, note=note)
    return await _render_list(request)


@router.post("/prompt-library/{name}/deprecate", response_class=HTMLResponse)
async def library_deprecate(
    request: Request, name: str,
    actor: str = Form(""), note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request)
    try:
        await svc.deprecate(name, actor=actor, note=note)
    except ValueError:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return await _render_list(request)


@router.post("/prompt-library/{name}/restore", response_class=HTMLResponse)
async def library_restore(
    request: Request, name: str,
    actor: str = Form(""), note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request)
    try:
        await svc.restore(name, actor=actor, note=note)
    except ValueError:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return await _render_list(request)


@router.get("/prompt-library/audit", response_class=HTMLResponse)
async def library_audit(
    request: Request, name: str = "",
) -> HTMLResponse:
    svc = _service(request)
    entries = await svc.list_audit(name=name or None)
    return render_fragment_or_page(
        request,
        "prompt_library_audit_fragment.html",
        {"request": request, "entries": entries, "name": name},
        page_title="Prompt Library — Audit",
    )
