"""TechLead dashboard routes (Phase D).

- ``GET  /projects/{pid}/deps`` — dependency radar fragment.
- ``POST /projects/{pid}/deps/scan`` — run registered scanners now.
- ``POST /projects/{pid}/deps/{finding_id}/dismiss`` — dismiss a finding.
- ``GET  /projects/{pid}/adrs`` — ADR browser fragment.
- ``POST /projects/{pid}/adrs`` — create an ADR.
- ``GET  /projects/{pid}/adrs/{adr_id}`` — full ADR view.
- ``POST /projects/{pid}/adrs/{adr_id}/accept`` — mark accepted.
- ``POST /projects/{pid}/adrs/{adr_id}/reject`` — mark rejected.
- ``GET  /projects/{pid}/debt`` — debt register fragment.
- ``POST /projects/{pid}/debt`` — add a debt entry.
- ``POST /projects/{pid}/debt/{id}/resolve`` — mark resolved.
- ``GET  /projects/{pid}/reviews/calibration`` — calibration stats fragment.
- ``GET  /projects/{pid}/critical-paths`` — critical-path manager fragment.
- ``POST /projects/{pid}/critical-paths`` — add critical path.
- ``POST /projects/{pid}/critical-paths/{id}/delete`` — remove path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.techlead.value_objects import DebtSeverity

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _adr_service(request: Request):
    svc = getattr(request.app.state, "adr_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="adr service not configured")
    return svc


def _debt_service(request: Request):
    svc = getattr(request.app.state, "debt_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="debt service not configured")
    return svc


def _dep_repo(request: Request):
    return getattr(request.app.state, "dep_finding_repo", None)


def _dep_radar(request: Request):
    return getattr(request.app.state, "dependency_radar", None)


def _calibration_service(request: Request):
    svc = getattr(request.app.state, "review_calibration_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="calibration service not configured")
    return svc


def _second_opinion_service(request: Request):
    svc = getattr(request.app.state, "second_opinion_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="second-opinion service not configured")
    return svc


# ── Dependency radar ────────────────────────────────────────────────


@router.get("/projects/{project_id}/deps", response_class=HTMLResponse)
async def project_deps(request: Request, project_id: str) -> HTMLResponse:
    repo = _dep_repo(request)
    findings = await repo.list_for_project(project_id) if repo is not None else []
    radar = _dep_radar(request)
    scanners = sorted(radar._scanners.keys()) if radar is not None else []
    return _templates(request).TemplateResponse(
        "deps_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "findings": findings,
            "scanners": scanners,
        },
    )


@router.post("/projects/{project_id}/deps/scan", response_class=HTMLResponse)
async def project_deps_scan(request: Request, project_id: str) -> HTMLResponse:
    radar = _dep_radar(request)
    if radar is None:
        raise HTTPException(status_code=503, detail="dependency radar not configured")
    for name, scanner in list(radar._scanners.items()):
        await radar.scan_project(project_id, name, scanner)
    return await project_deps(request, project_id)


@router.post(
    "/projects/{project_id}/deps/{finding_id}/dismiss",
    response_class=HTMLResponse,
)
async def project_dismiss_finding(
    request: Request, project_id: str, finding_id: str,
) -> HTMLResponse:
    repo = _dep_repo(request)
    if repo is not None:
        await repo.dismiss(finding_id)
    return await project_deps(request, project_id)


# ── ADRs ────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/adrs", response_class=HTMLResponse)
async def project_adrs(request: Request, project_id: str) -> HTMLResponse:
    svc = _adr_service(request)
    adrs = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "adrs_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "adrs": adrs,
        },
    )


@router.post("/projects/{project_id}/adrs", response_class=HTMLResponse)
async def project_create_adr(
    request: Request,
    project_id: str,
    title: str = Form(...),
    context: str = Form(""),
    decision: str = Form(""),
    consequences: str = Form(""),
) -> HTMLResponse:
    svc = _adr_service(request)
    await svc.propose(
        project_id=project_id,
        title=title,
        context=context,
        decision=decision,
        consequences=consequences,
    )
    return await project_adrs(request, project_id)


@router.get(
    "/projects/{project_id}/adrs/{adr_id}",
    response_class=HTMLResponse,
)
async def project_adr_detail(
    request: Request, project_id: str, adr_id: str,
) -> HTMLResponse:
    svc = _adr_service(request)
    adr = None
    for item in await svc.list(project_id):
        if item.id == adr_id:
            adr = item
            break
    if adr is None:
        raise HTTPException(status_code=404, detail="ADR not found")
    return _templates(request).TemplateResponse(
        "adr_detail.html",
        {"request": request, "project_id": project_id, "adr": adr},
    )


@router.post(
    "/projects/{project_id}/adrs/{adr_id}/accept",
    response_class=HTMLResponse,
)
async def project_accept_adr(
    request: Request, project_id: str, adr_id: str,
) -> HTMLResponse:
    svc = _adr_service(request)
    await svc.accept(adr_id)
    return await project_adrs(request, project_id)


@router.post(
    "/projects/{project_id}/adrs/{adr_id}/reject",
    response_class=HTMLResponse,
)
async def project_reject_adr(
    request: Request, project_id: str, adr_id: str,
) -> HTMLResponse:
    svc = _adr_service(request)
    await svc.reject(adr_id)
    return await project_adrs(request, project_id)


# ── Debt register ───────────────────────────────────────────────────


@router.get("/projects/{project_id}/debt", response_class=HTMLResponse)
async def project_debt(request: Request, project_id: str) -> HTMLResponse:
    svc = _debt_service(request)
    items = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "debt_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "items": items,
        },
    )


@router.post("/projects/{project_id}/debt", response_class=HTMLResponse)
async def project_add_debt(
    request: Request,
    project_id: str,
    title: str = Form(...),
    severity: str = Form("medium"),
    blast_radius: str = Form(""),
    location: str = Form(""),
    description: str = Form(""),
) -> HTMLResponse:
    svc = _debt_service(request)
    try:
        sev = DebtSeverity(severity)
    except ValueError:
        sev = DebtSeverity.MEDIUM
    await svc.add(
        project_id=project_id,
        title=title,
        severity=sev,
        blast_radius=blast_radius,
        location=location,
        description=description,
    )
    return await project_debt(request, project_id)


@router.post(
    "/projects/{project_id}/debt/{debt_id}/resolve",
    response_class=HTMLResponse,
)
async def project_resolve_debt(
    request: Request, project_id: str, debt_id: str,
) -> HTMLResponse:
    svc = _debt_service(request)
    await svc.resolve(debt_id)
    return await project_debt(request, project_id)


# ── Review calibration ──────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/reviews/calibration", response_class=HTMLResponse,
)
async def project_reviews_calibration(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _calibration_service(request)
    stats = await svc.stats(project_id)
    return _templates(request).TemplateResponse(
        "reviews_calibration_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "stats": stats,
        },
    )


# ── Critical paths ──────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/critical-paths", response_class=HTMLResponse,
)
async def project_critical_paths(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _second_opinion_service(request)
    paths = await svc.list_critical_paths(project_id)
    return _templates(request).TemplateResponse(
        "critical_paths_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "paths": paths,
        },
    )


@router.post(
    "/projects/{project_id}/critical-paths", response_class=HTMLResponse,
)
async def project_add_critical_path(
    request: Request,
    project_id: str,
    pattern: str = Form(...),
    reason: str = Form(""),
) -> HTMLResponse:
    svc = _second_opinion_service(request)
    if pattern.strip():
        await svc.add_critical_path(project_id, pattern, reason)
    return await project_critical_paths(request, project_id)


@router.post(
    "/projects/{project_id}/critical-paths/{path_id}/delete",
    response_class=HTMLResponse,
)
async def project_delete_critical_path(
    request: Request, project_id: str, path_id: str,
) -> HTMLResponse:
    svc = _second_opinion_service(request)
    await svc.remove_critical_path(path_id)
    return await project_critical_paths(request, project_id)
