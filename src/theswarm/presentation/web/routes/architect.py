"""Architect dashboard routes (Phase K).

Surfaces paved-road rules (portfolio-wide) and ADRs + direction briefs
that can be portfolio-wide or project-scoped.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.architect.value_objects import (
    ADRStatus,
    BriefScope,
    RuleSeverity,
)
from theswarm.presentation.web.fragment_response import render_fragment_or_page

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _service(request: Request, attr: str, label: str):
    svc = getattr(request.app.state, attr, None)
    if svc is None:
        raise HTTPException(status_code=503, detail=f"{label} not configured")
    return svc


def _parse_tags(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(t for t in (s.strip() for s in text.split(",")) if t)


def _parse_lines(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(ln for ln in (s.strip() for s in text.splitlines()) if ln)


# ── Paved road (portfolio-wide) ────────────────────────────────────


@router.get("/architect/paved-road", response_class=HTMLResponse)
async def paved_road(request: Request) -> HTMLResponse:
    svc = _service(request, "paved_road_service", "paved road service")
    rules = await svc.list()
    return render_fragment_or_page(
        request,
        "architect_paved_road_fragment.html",
        {
            "request": request,
            "rules": rules,
            "severities": list(RuleSeverity),
        },
        page_title="Architect — Paved Road",
    )


@router.post("/architect/paved-road", response_class=HTMLResponse)
async def paved_road_upsert(
    request: Request,
    name: str = Form(...),
    rule: str = Form(...),
    rationale: str = Form(""),
    severity: str = Form("advisory"),
    tags: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "paved_road_service", "paved road service")
    try:
        sev_enum = RuleSeverity(severity)
    except ValueError:
        sev_enum = RuleSeverity.ADVISORY
    await svc.upsert(
        name=name, rule=rule, rationale=rationale,
        severity=sev_enum, tags=_parse_tags(tags),
    )
    return await paved_road(request)


# ── Portfolio ADRs ─────────────────────────────────────────────────


@router.get("/architect/adrs", response_class=HTMLResponse)
async def portfolio_adrs(request: Request) -> HTMLResponse:
    svc = _service(request, "portfolio_adr_service", "ADR service")
    adrs = await svc.list()
    return render_fragment_or_page(
        request,
        "architect_adrs_fragment.html",
        {
            "request": request,
            "adrs": adrs,
            "statuses": list(ADRStatus),
            "scope_label": "portfolio",
            "project_id": "",
        },
        page_title="Architect — Portfolio ADRs",
    )


@router.get(
    "/projects/{project_id}/architect/adrs", response_class=HTMLResponse,
)
async def project_adrs(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "portfolio_adr_service", "ADR service")
    adrs = await svc.list(project_id=project_id)
    return _templates(request).TemplateResponse(
        "architect_adrs_fragment.html",
        {
            "request": request,
            "adrs": adrs,
            "statuses": list(ADRStatus),
            "scope_label": "project",
            "project_id": project_id,
        },
    )


@router.post("/architect/adrs", response_class=HTMLResponse)
async def propose_portfolio_adr(
    request: Request,
    title: str = Form(...),
    context: str = Form(""),
    decision: str = Form(""),
    consequences: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "portfolio_adr_service", "ADR service")
    await svc.propose(
        title=title, context=context, decision=decision,
        consequences=consequences, project_id="",
    )
    return await portfolio_adrs(request)


@router.post(
    "/projects/{project_id}/architect/adrs", response_class=HTMLResponse,
)
async def propose_project_adr(
    request: Request,
    project_id: str,
    title: str = Form(...),
    context: str = Form(""),
    decision: str = Form(""),
    consequences: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "portfolio_adr_service", "ADR service")
    await svc.propose(
        title=title, context=context, decision=decision,
        consequences=consequences, project_id=project_id,
    )
    return await project_adrs(request, project_id)


@router.post("/architect/adrs/{adr_id}/accept", response_class=HTMLResponse)
async def accept_adr(
    request: Request, adr_id: str,
) -> HTMLResponse:
    svc = _service(request, "portfolio_adr_service", "ADR service")
    try:
        adr = await svc.accept(adr_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="ADR not found")
    if adr.project_id:
        return await project_adrs(request, adr.project_id)
    return await portfolio_adrs(request)


@router.post("/architect/adrs/{adr_id}/reject", response_class=HTMLResponse)
async def reject_adr(
    request: Request, adr_id: str,
) -> HTMLResponse:
    svc = _service(request, "portfolio_adr_service", "ADR service")
    try:
        adr = await svc.reject(adr_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="ADR not found")
    if adr.project_id:
        return await project_adrs(request, adr.project_id)
    return await portfolio_adrs(request)


# ── Direction briefs ───────────────────────────────────────────────


@router.get("/architect/briefs", response_class=HTMLResponse)
async def portfolio_briefs(request: Request) -> HTMLResponse:
    svc = _service(
        request, "direction_brief_service", "direction brief service",
    )
    briefs = await svc.list_portfolio()
    return render_fragment_or_page(
        request,
        "architect_briefs_fragment.html",
        {
            "request": request,
            "briefs": briefs,
            "scope_label": "portfolio",
            "project_id": "",
        },
        page_title="Architect — Direction Briefs",
    )


@router.get(
    "/projects/{project_id}/architect/briefs", response_class=HTMLResponse,
)
async def project_briefs(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(
        request, "direction_brief_service", "direction brief service",
    )
    briefs = await svc.list_for_project(project_id)
    return _templates(request).TemplateResponse(
        "architect_briefs_fragment.html",
        {
            "request": request,
            "briefs": briefs,
            "scope_label": "project",
            "project_id": project_id,
        },
    )


@router.post("/architect/briefs", response_class=HTMLResponse)
async def record_portfolio_brief(
    request: Request,
    title: str = Form(...),
    period: str = Form(""),
    author: str = Form(""),
    focus_areas: str = Form(""),
    risks: str = Form(""),
    narrative: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "direction_brief_service", "direction brief service",
    )
    await svc.record(
        title=title, scope=BriefScope.PORTFOLIO,
        period=period, author=author,
        focus_areas=_parse_lines(focus_areas),
        risks=_parse_lines(risks),
        narrative=narrative,
    )
    return await portfolio_briefs(request)


@router.post(
    "/projects/{project_id}/architect/briefs", response_class=HTMLResponse,
)
async def record_project_brief(
    request: Request,
    project_id: str,
    title: str = Form(...),
    period: str = Form(""),
    author: str = Form(""),
    focus_areas: str = Form(""),
    risks: str = Form(""),
    narrative: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "direction_brief_service", "direction brief service",
    )
    await svc.record(
        title=title, scope=BriefScope.PROJECT, project_id=project_id,
        period=period, author=author,
        focus_areas=_parse_lines(focus_areas),
        risks=_parse_lines(risks),
        narrative=narrative,
    )
    return await project_briefs(request, project_id)
