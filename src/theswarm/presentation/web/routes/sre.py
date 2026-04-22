"""SRE dashboard routes (Phase I).

Surfaces deployments, incidents, and unified cost rollup per project.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.sre.value_objects import (
    CostSource,
    IncidentSeverity,
)

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _service(request: Request, attr: str, label: str):
    svc = getattr(request.app.state, attr, None)
    if svc is None:
        raise HTTPException(status_code=503, detail=f"{label} not configured")
    return svc


# ── Deployments ────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/sre/deployments", response_class=HTMLResponse,
)
async def project_deployments(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "deployment_service", "deployment service")
    deployments = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "sre_deployments_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "deployments": deployments,
        },
    )


@router.post(
    "/projects/{project_id}/sre/deployments", response_class=HTMLResponse,
)
async def project_start_deployment(
    request: Request,
    project_id: str,
    version: str = Form(""),
    environment: str = Form("production"),
    triggered_by: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "deployment_service", "deployment service")
    await svc.start(
        project_id=project_id, environment=environment,
        version=version, triggered_by=triggered_by, notes=notes,
    )
    return await project_deployments(request, project_id)


@router.post(
    "/projects/{project_id}/sre/deployments/{deployment_id}/succeed",
    response_class=HTMLResponse,
)
async def project_succeed_deployment(
    request: Request,
    project_id: str,
    deployment_id: str,
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "deployment_service", "deployment service")
    await svc.succeed(deployment_id, notes=notes)
    return await project_deployments(request, project_id)


@router.post(
    "/projects/{project_id}/sre/deployments/{deployment_id}/fail",
    response_class=HTMLResponse,
)
async def project_fail_deployment(
    request: Request,
    project_id: str,
    deployment_id: str,
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "deployment_service", "deployment service")
    await svc.fail(deployment_id, notes=notes)
    return await project_deployments(request, project_id)


@router.post(
    "/projects/{project_id}/sre/deployments/{deployment_id}/rollback",
    response_class=HTMLResponse,
)
async def project_rollback_deployment(
    request: Request,
    project_id: str,
    deployment_id: str,
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "deployment_service", "deployment service")
    await svc.rollback(deployment_id, notes=notes)
    return await project_deployments(request, project_id)


# ── Incidents ──────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/sre/incidents", response_class=HTMLResponse,
)
async def project_incidents(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "incident_service", "incident service")
    incidents = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "sre_incidents_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "incidents": incidents,
            "severities": list(IncidentSeverity),
        },
    )


@router.post(
    "/projects/{project_id}/sre/incidents", response_class=HTMLResponse,
)
async def project_open_incident(
    request: Request,
    project_id: str,
    title: str = Form(...),
    severity: str = Form("sev3"),
    summary: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "incident_service", "incident service")
    try:
        sev_enum = IncidentSeverity(severity)
    except ValueError:
        sev_enum = IncidentSeverity.SEV3
    await svc.open(
        project_id=project_id, title=title, severity=sev_enum, summary=summary,
    )
    return await project_incidents(request, project_id)


@router.post(
    "/projects/{project_id}/sre/incidents/{incident_id}/triage",
    response_class=HTMLResponse,
)
async def project_triage_incident(
    request: Request,
    project_id: str,
    incident_id: str,
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "incident_service", "incident service")
    await svc.triage(incident_id, note=note)
    return await project_incidents(request, project_id)


@router.post(
    "/projects/{project_id}/sre/incidents/{incident_id}/mitigate",
    response_class=HTMLResponse,
)
async def project_mitigate_incident(
    request: Request,
    project_id: str,
    incident_id: str,
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "incident_service", "incident service")
    await svc.mitigate(incident_id, note=note)
    return await project_incidents(request, project_id)


@router.post(
    "/projects/{project_id}/sre/incidents/{incident_id}/resolve",
    response_class=HTMLResponse,
)
async def project_resolve_incident(
    request: Request,
    project_id: str,
    incident_id: str,
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "incident_service", "incident service")
    await svc.resolve(incident_id, note=note)
    return await project_incidents(request, project_id)


@router.post(
    "/projects/{project_id}/sre/incidents/{incident_id}/postmortem",
    response_class=HTMLResponse,
)
async def project_postmortem_incident(
    request: Request,
    project_id: str,
    incident_id: str,
    postmortem: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "incident_service", "incident service")
    await svc.write_postmortem(incident_id, postmortem=postmortem)
    return await project_incidents(request, project_id)


@router.post(
    "/projects/{project_id}/sre/incidents/{incident_id}/timeline",
    response_class=HTMLResponse,
)
async def project_append_incident_timeline(
    request: Request,
    project_id: str,
    incident_id: str,
    note: str = Form(...),
) -> HTMLResponse:
    svc = _service(request, "incident_service", "incident service")
    await svc.add_timeline(incident_id, note=note)
    return await project_incidents(request, project_id)


# ── Cost ───────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/sre/cost", response_class=HTMLResponse,
)
async def project_cost(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "cost_service", "cost service")
    rollup = await svc.rollup(project_id)
    samples = await svc.list(project_id, limit=20)
    total = sum(rollup.values())
    return _templates(request).TemplateResponse(
        "sre_cost_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "rollup": rollup,
            "total": total,
            "samples": samples,
            "sources": list(CostSource),
        },
    )


@router.post(
    "/projects/{project_id}/sre/cost", response_class=HTMLResponse,
)
async def project_record_cost(
    request: Request,
    project_id: str,
    source: str = Form("infra"),
    amount_usd: float = Form(0.0),
    window: str = Form("daily"),
    description: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "cost_service", "cost service")
    try:
        src_enum = CostSource(source)
    except ValueError:
        src_enum = CostSource.OTHER
    await svc.record(
        project_id=project_id, source=src_enum, amount_usd=amount_usd,
        window=window, description=description,
    )
    return await project_cost(request, project_id)
