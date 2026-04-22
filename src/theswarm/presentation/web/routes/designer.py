"""Designer dashboard routes (Phase H).

Surfaces design tokens, component inventory, design briefs, visual
regression records, and anti-template ship-bar checks per project.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.designer.value_objects import (
    BriefStatus,
    CheckStatus,
    ComponentStatus,
    TokenKind,
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


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


# ── Design tokens ──────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/design/tokens", response_class=HTMLResponse,
)
async def project_design_tokens(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "design_system_service", "design-system service")
    tokens = await svc.list_tokens(project_id)
    return _templates(request).TemplateResponse(
        "design_tokens_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "tokens": tokens,
            "kinds": list(TokenKind),
        },
    )


@router.post(
    "/projects/{project_id}/design/tokens", response_class=HTMLResponse,
)
async def project_set_design_token(
    request: Request,
    project_id: str,
    name: str = Form(...),
    kind: str = Form("other"),
    value: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "design_system_service", "design-system service")
    try:
        kind_enum = TokenKind(kind)
    except ValueError:
        kind_enum = TokenKind.OTHER
    await svc.set_token(
        project_id=project_id,
        name=name,
        kind=kind_enum,
        value=value,
        notes=notes,
    )
    return await project_design_tokens(request, project_id)


# ── Component inventory ────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/design/components", response_class=HTMLResponse,
)
async def project_components(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(
        request, "component_inventory_service", "component-inventory service",
    )
    entries = await svc.list_inventory(project_id)
    return _templates(request).TemplateResponse(
        "design_components_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "entries": entries,
            "statuses": list(ComponentStatus),
        },
    )


@router.post(
    "/projects/{project_id}/design/components", response_class=HTMLResponse,
)
async def project_register_component(
    request: Request,
    project_id: str,
    name: str = Form(...),
    status: str = Form("proposed"),
    path: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "component_inventory_service", "component-inventory service",
    )
    try:
        status_enum = ComponentStatus(status)
    except ValueError:
        status_enum = ComponentStatus.PROPOSED
    await svc.register(
        project_id=project_id, name=name, status=status_enum,
        path=path, notes=notes,
    )
    return await project_components(request, project_id)


@router.post(
    "/projects/{project_id}/design/components/{name}/promote",
    response_class=HTMLResponse,
)
async def project_promote_component(
    request: Request, project_id: str, name: str,
) -> HTMLResponse:
    svc = _service(
        request, "component_inventory_service", "component-inventory service",
    )
    await svc.promote(project_id=project_id, name=name)
    return await project_components(request, project_id)


@router.post(
    "/projects/{project_id}/design/components/{name}/deprecate",
    response_class=HTMLResponse,
)
async def project_deprecate_component(
    request: Request, project_id: str, name: str,
) -> HTMLResponse:
    svc = _service(
        request, "component_inventory_service", "component-inventory service",
    )
    await svc.deprecate(project_id=project_id, name=name)
    return await project_components(request, project_id)


# ── Design briefs ──────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/design/briefs", response_class=HTMLResponse,
)
async def project_design_briefs(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "design_brief_service", "design-brief service")
    briefs = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "design_briefs_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "briefs": briefs,
            "statuses": list(BriefStatus),
        },
    )


@router.post(
    "/projects/{project_id}/design/briefs", response_class=HTMLResponse,
)
async def project_draft_design_brief(
    request: Request,
    project_id: str,
    story_id: str = Form(...),
    title: str = Form(""),
    intent: str = Form(""),
    hierarchy: str = Form(""),
    states: str = Form(""),
    motion: str = Form(""),
    reference_url: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "design_brief_service", "design-brief service")
    await svc.draft(
        project_id=project_id,
        story_id=story_id,
        title=title,
        intent=intent,
        hierarchy=hierarchy,
        states=states,
        motion=motion,
        reference_url=reference_url,
    )
    return await project_design_briefs(request, project_id)


@router.post(
    "/projects/{project_id}/design/briefs/{story_id}/status",
    response_class=HTMLResponse,
)
async def project_update_brief_status(
    request: Request,
    project_id: str,
    story_id: str,
    status: str = Form(...),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "design_brief_service", "design-brief service")
    try:
        status_enum = BriefStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="unknown status") from exc
    if status_enum == BriefStatus.READY:
        await svc.mark_ready(project_id=project_id, story_id=story_id)
    elif status_enum == BriefStatus.APPROVED:
        await svc.approve(project_id=project_id, story_id=story_id, note=note)
    elif status_enum == BriefStatus.CHANGES_REQUESTED:
        await svc.request_changes(
            project_id=project_id, story_id=story_id, note=note,
        )
    # DRAFT is a no-op here; drafts are created via POST above.
    return await project_design_briefs(request, project_id)


# ── Visual regression ──────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/design/visual-regressions",
    response_class=HTMLResponse,
)
async def project_visual_regressions(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(
        request, "visual_regression_service", "visual-regression service",
    )
    entries = await svc.list_for_project(project_id, limit=50)
    return _templates(request).TemplateResponse(
        "design_vr_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "entries": entries,
            "statuses": list(CheckStatus),
        },
    )


@router.post(
    "/projects/{project_id}/design/visual-regressions",
    response_class=HTMLResponse,
)
async def project_capture_vr(
    request: Request,
    project_id: str,
    story_id: str = Form(""),
    viewport: str = Form(""),
    before_path: str = Form(""),
    after_path: str = Form(""),
    mask_notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "visual_regression_service", "visual-regression service",
    )
    await svc.capture(
        project_id=project_id,
        story_id=story_id,
        viewport=viewport,
        before_path=before_path,
        after_path=after_path,
        mask_notes=mask_notes,
    )
    return await project_visual_regressions(request, project_id)


@router.post(
    "/projects/{project_id}/design/visual-regressions/{entry_id}/review",
    response_class=HTMLResponse,
)
async def project_review_vr(
    request: Request,
    project_id: str,
    entry_id: str,
    status: str = Form(...),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "visual_regression_service", "visual-regression service",
    )
    try:
        status_enum = CheckStatus(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="unknown status") from exc
    await svc.review(entry_id=entry_id, status=status_enum, note=note)
    return await project_visual_regressions(request, project_id)


# ── Anti-template checks ───────────────────────────────────────────


@router.get(
    "/projects/{project_id}/design/anti-template",
    response_class=HTMLResponse,
)
async def project_anti_template(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "anti_template_service", "anti-template service")
    entries = await svc.list(project_id, limit=30)
    return _templates(request).TemplateResponse(
        "design_anti_template_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "entries": entries,
        },
    )


@router.post(
    "/projects/{project_id}/design/anti-template",
    response_class=HTMLResponse,
)
async def project_record_anti_template(
    request: Request,
    project_id: str,
    story_id: str = Form(""),
    pr_url: str = Form(""),
    qualities: str = Form(""),
    violations: str = Form(""),
    summary: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "anti_template_service", "anti-template service")
    await svc.record(
        project_id=project_id,
        story_id=story_id,
        pr_url=pr_url,
        qualities=_split_csv(qualities),
        violations=_split_csv(violations),
        summary=summary,
    )
    return await project_anti_template(request, project_id)
