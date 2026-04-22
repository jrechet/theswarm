"""Security dashboard routes (Phase I).

Surfaces threat model, data inventory, findings, SBOM, and AuthZ per project.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.security.value_objects import (
    AuthZEffect,
    DataClass,
    FindingSeverity,
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


# ── Threat model ───────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/security/threat-model",
    response_class=HTMLResponse,
)
async def project_threat_model(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "threat_model_service", "threat-model service")
    tm = await svc.get(project_id)
    return _templates(request).TemplateResponse(
        "security_threat_model_fragment.html",
        {"request": request, "project_id": project_id, "threat_model": tm},
    )


@router.post(
    "/projects/{project_id}/security/threat-model",
    response_class=HTMLResponse,
)
async def project_upsert_threat_model(
    request: Request,
    project_id: str,
    title: str = Form(""),
    assets: str = Form(""),
    actors: str = Form(""),
    trust_boundaries: str = Form(""),
    stride_notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "threat_model_service", "threat-model service")
    await svc.upsert(
        project_id=project_id, title=title, assets=assets, actors=actors,
        trust_boundaries=trust_boundaries, stride_notes=stride_notes,
    )
    return await project_threat_model(request, project_id)


# ── Data inventory ─────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/security/data-inventory",
    response_class=HTMLResponse,
)
async def project_data_inventory(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "data_inventory_service", "data-inventory service")
    entries = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "security_data_inventory_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "entries": entries,
            "classes": list(DataClass),
        },
    )


@router.post(
    "/projects/{project_id}/security/data-inventory",
    response_class=HTMLResponse,
)
async def project_upsert_data_entry(
    request: Request,
    project_id: str,
    field_name: str = Form(...),
    classification: str = Form("internal"),
    storage_notes: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "data_inventory_service", "data-inventory service")
    try:
        cls_enum = DataClass(classification)
    except ValueError:
        cls_enum = DataClass.INTERNAL
    await svc.upsert(
        project_id=project_id, field_name=field_name,
        classification=cls_enum, storage_notes=storage_notes, notes=notes,
    )
    return await project_data_inventory(request, project_id)


# ── Security findings ──────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/security/findings", response_class=HTMLResponse,
)
async def project_findings(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "security_finding_service", "finding service")
    findings = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "security_findings_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "findings": findings,
            "severities": list(FindingSeverity),
        },
    )


@router.post(
    "/projects/{project_id}/security/findings", response_class=HTMLResponse,
)
async def project_open_finding(
    request: Request,
    project_id: str,
    title: str = Form(...),
    severity: str = Form("medium"),
    description: str = Form(""),
    cve: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "security_finding_service", "finding service")
    try:
        sev_enum = FindingSeverity(severity)
    except ValueError:
        sev_enum = FindingSeverity.MEDIUM
    await svc.open(
        project_id=project_id, severity=sev_enum, title=title,
        description=description, cve=cve,
    )
    return await project_findings(request, project_id)


@router.post(
    "/projects/{project_id}/security/findings/{finding_id}/resolve",
    response_class=HTMLResponse,
)
async def project_resolve_finding(
    request: Request,
    project_id: str,
    finding_id: str,
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "security_finding_service", "finding service")
    await svc.resolve(finding_id, note=note)
    return await project_findings(request, project_id)


@router.post(
    "/projects/{project_id}/security/findings/{finding_id}/triage",
    response_class=HTMLResponse,
)
async def project_triage_finding(
    request: Request,
    project_id: str,
    finding_id: str,
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "security_finding_service", "finding service")
    await svc.triage(finding_id, note=note)
    return await project_findings(request, project_id)


# ── SBOM ───────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/security/sbom", response_class=HTMLResponse,
)
async def project_sbom(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "sbom_service", "sbom service")
    artifacts = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "security_sbom_fragment.html",
        {"request": request, "project_id": project_id, "artifacts": artifacts},
    )


@router.post(
    "/projects/{project_id}/security/sbom", response_class=HTMLResponse,
)
async def project_record_sbom(
    request: Request,
    project_id: str,
    tool: str = Form("syft"),
    cycle_id: str = Form(""),
    package_count: int = Form(0),
    license_summary: str = Form(""),
    artifact_path: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "sbom_service", "sbom service")
    await svc.record(
        project_id=project_id, tool=tool, cycle_id=cycle_id,
        package_count=package_count, license_summary=license_summary,
        artifact_path=artifact_path,
    )
    return await project_sbom(request, project_id)


# ── AuthZ matrix ───────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/security/authz", response_class=HTMLResponse,
)
async def project_authz(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "authz_service", "authz service")
    rules = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "security_authz_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "rules": rules,
            "effects": list(AuthZEffect),
        },
    )


@router.post(
    "/projects/{project_id}/security/authz", response_class=HTMLResponse,
)
async def project_upsert_authz(
    request: Request,
    project_id: str,
    actor_role: str = Form(...),
    resource: str = Form(...),
    action: str = Form(...),
    effect: str = Form("allow"),
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "authz_service", "authz service")
    try:
        eff_enum = AuthZEffect(effect)
    except ValueError:
        eff_enum = AuthZEffect.ALLOW
    await svc.upsert(
        project_id=project_id, actor_role=actor_role, resource=resource,
        action=action, effect=eff_enum, notes=notes,
    )
    return await project_authz(request, project_id)
