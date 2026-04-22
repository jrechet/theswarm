"""Semantic memory dashboard routes (Phase L).

Portfolio-wide + project-scoped listing; opt-in enable/disable per entry.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _service(request: Request):
    svc = getattr(request.app.state, "semantic_memory_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503, detail="semantic memory service not configured",
        )
    return svc


def _parse_tags(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(t for t in (s.strip() for s in text.split(",")) if t)


def _render(request, entries, *, project_id, query, tag):
    return _templates(request).TemplateResponse(
        "semantic_memory_fragment.html",
        {
            "request": request,
            "entries": entries,
            "project_id": project_id,
            "query": query,
            "tag": tag,
        },
    )


# ── Portfolio ──────────────────────────────────────────────────────


@router.get("/semantic-memory", response_class=HTMLResponse)
async def memory_list(
    request: Request, q: str = "", tag: str = "",
) -> HTMLResponse:
    svc = _service(request)
    if q or tag:
        entries = await svc.search(query=q, tag=tag)
    else:
        entries = await svc.list()
    return _render(request, entries, project_id="", query=q, tag=tag)


@router.post("/semantic-memory", response_class=HTMLResponse)
async def memory_record(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    project_id: str = Form(""),
    tags: str = Form(""),
    enabled: str = Form("1"),
    source: str = Form(""),
) -> HTMLResponse:
    svc = _service(request)
    await svc.record(
        title=title, content=content, project_id=project_id,
        tags=_parse_tags(tags),
        enabled=enabled in ("1", "true", "on"),
        source=source,
    )
    if project_id:
        entries = await svc.list(project_id=project_id)
        return _render(request, entries, project_id=project_id, query="", tag="")
    entries = await svc.list()
    return _render(request, entries, project_id="", query="", tag="")


@router.post(
    "/semantic-memory/{entry_id}/enable", response_class=HTMLResponse,
)
async def memory_enable(
    request: Request, entry_id: str,
    enabled: str = Form("1"),
) -> HTMLResponse:
    svc = _service(request)
    try:
        updated = await svc.set_enabled(
            entry_id, enabled in ("1", "true", "on"),
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    if updated.project_id:
        entries = await svc.list(project_id=updated.project_id)
        return _render(
            request, entries, project_id=updated.project_id,
            query="", tag="",
        )
    entries = await svc.list()
    return _render(request, entries, project_id="", query="", tag="")


# ── Project-scoped ─────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/semantic-memory",
    response_class=HTMLResponse,
)
async def project_memory_list(
    request: Request, project_id: str, q: str = "", tag: str = "",
) -> HTMLResponse:
    svc = _service(request)
    if q or tag:
        entries = await svc.search(
            query=q, tag=tag, project_id=project_id,
        )
    else:
        entries = await svc.list(project_id=project_id)
    return _render(
        request, entries, project_id=project_id, query=q, tag=tag,
    )


@router.post(
    "/projects/{project_id}/semantic-memory",
    response_class=HTMLResponse,
)
async def project_memory_record(
    request: Request, project_id: str,
    title: str = Form(...),
    content: str = Form(""),
    tags: str = Form(""),
    enabled: str = Form("1"),
    source: str = Form(""),
) -> HTMLResponse:
    svc = _service(request)
    await svc.record(
        title=title, content=content, project_id=project_id,
        tags=_parse_tags(tags),
        enabled=enabled in ("1", "true", "on"),
        source=source,
    )
    entries = await svc.list(project_id=project_id)
    return _render(
        request, entries, project_id=project_id, query="", tag="",
    )
