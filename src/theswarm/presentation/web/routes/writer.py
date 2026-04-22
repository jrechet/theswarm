"""Writer dashboard routes (Phase J).

Surfaces doc artifacts, quickstart checks, and changelog entries per project.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.writer.value_objects import (
    ChangeKind,
    DocKind,
    DocStatus,
    QuickstartOutcome,
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


# ── Doc artifacts ──────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/writer/docs", response_class=HTMLResponse,
)
async def project_docs(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "doc_artifact_service", "doc service")
    docs = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "writer_docs_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "docs": docs,
            "kinds": list(DocKind),
            "statuses": list(DocStatus),
        },
    )


@router.post(
    "/projects/{project_id}/writer/docs", response_class=HTMLResponse,
)
async def project_upsert_doc(
    request: Request,
    project_id: str,
    path: str = Form(...),
    kind: str = Form("readme"),
    title: str = Form(""),
    summary: str = Form(""),
    status: str = Form("draft"),
) -> HTMLResponse:
    svc = _service(request, "doc_artifact_service", "doc service")
    try:
        kind_enum = DocKind(kind)
    except ValueError:
        kind_enum = DocKind.README
    try:
        status_enum = DocStatus(status)
    except ValueError:
        status_enum = DocStatus.DRAFT
    await svc.upsert(
        project_id=project_id, path=path, kind=kind_enum,
        title=title, summary=summary, status=status_enum,
    )
    return await project_docs(request, project_id)


@router.post(
    "/projects/{project_id}/writer/docs/status", response_class=HTMLResponse,
)
async def project_mark_doc_status(
    request: Request,
    project_id: str,
    path: str = Form(...),
    status: str = Form(...),
) -> HTMLResponse:
    svc = _service(request, "doc_artifact_service", "doc service")
    try:
        status_enum = DocStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="unknown status")
    await svc.mark_status(project_id, path, status_enum)
    return await project_docs(request, project_id)


# ── Quickstart checks ──────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/writer/quickstart", response_class=HTMLResponse,
)
async def project_quickstart(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "quickstart_check_service", "quickstart service")
    checks = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "writer_quickstart_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "checks": checks,
            "outcomes": list(QuickstartOutcome),
        },
    )


@router.post(
    "/projects/{project_id}/writer/quickstart", response_class=HTMLResponse,
)
async def project_record_quickstart(
    request: Request,
    project_id: str,
    step_count: int = Form(0),
    duration_seconds: float = Form(0.0),
    outcome: str = Form("skipped"),
    failure_step: str = Form(""),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "quickstart_check_service", "quickstart service")
    try:
        outcome_enum = QuickstartOutcome(outcome)
    except ValueError:
        outcome_enum = QuickstartOutcome.SKIPPED
    await svc.record(
        project_id=project_id, step_count=step_count,
        duration_seconds=duration_seconds, outcome=outcome_enum,
        failure_step=failure_step, note=note,
    )
    return await project_quickstart(request, project_id)


# ── Changelog ──────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/writer/changelog", response_class=HTMLResponse,
)
async def project_changelog(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "changelog_service", "changelog service")
    entries = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "writer_changelog_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "entries": entries,
            "kinds": list(ChangeKind),
        },
    )


@router.post(
    "/projects/{project_id}/writer/changelog", response_class=HTMLResponse,
)
async def project_record_changelog(
    request: Request,
    project_id: str,
    kind: str = Form("feat"),
    summary: str = Form(...),
    pr_url: str = Form(""),
    version: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "changelog_service", "changelog service")
    try:
        kind_enum = ChangeKind(kind)
    except ValueError:
        kind_enum = ChangeKind.CHORE
    await svc.record(
        project_id=project_id, kind=kind_enum, summary=summary,
        pr_url=pr_url, version=version,
    )
    return await project_changelog(request, project_id)
