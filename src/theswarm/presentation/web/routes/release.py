"""Release dashboard routes (Phase J).

Surfaces release versions, feature flags, and rollback actions per project.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.release.value_objects import (
    FlagState,
    ReleaseStatus,
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


# ── Release versions ───────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/release/versions",
    response_class=HTMLResponse,
)
async def project_versions(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "release_version_service", "release service")
    versions = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "release_versions_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "versions": versions,
            "statuses": list(ReleaseStatus),
        },
    )


@router.post(
    "/projects/{project_id}/release/versions",
    response_class=HTMLResponse,
)
async def project_draft_version(
    request: Request,
    project_id: str,
    version: str = Form(...),
    summary: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "release_version_service", "release service")
    await svc.draft(project_id=project_id, version=version, summary=summary)
    return await project_versions(request, project_id)


@router.post(
    "/projects/{project_id}/release/versions/{version}/release",
    response_class=HTMLResponse,
)
async def project_mark_released(
    request: Request, project_id: str, version: str,
) -> HTMLResponse:
    svc = _service(request, "release_version_service", "release service")
    try:
        await svc.mark_released(project_id, version)
    except ValueError:
        raise HTTPException(status_code=404, detail="release not found")
    return await project_versions(request, project_id)


@router.post(
    "/projects/{project_id}/release/versions/{version}/rollback",
    response_class=HTMLResponse,
)
async def project_mark_rolled_back(
    request: Request, project_id: str, version: str,
) -> HTMLResponse:
    svc = _service(request, "release_version_service", "release service")
    try:
        await svc.mark_rolled_back(project_id, version)
    except ValueError:
        raise HTTPException(status_code=404, detail="release not found")
    return await project_versions(request, project_id)


# ── Feature flags ──────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/release/flags", response_class=HTMLResponse,
)
async def project_flags(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "feature_flag_service", "feature flag service")
    flags = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "release_flags_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "flags": flags,
            "states": list(FlagState),
        },
    )


@router.post(
    "/projects/{project_id}/release/flags", response_class=HTMLResponse,
)
async def project_upsert_flag(
    request: Request,
    project_id: str,
    name: str = Form(...),
    owner: str = Form(""),
    description: str = Form(""),
    state: str = Form("active"),
    rollout_percent: int = Form(0),
    cleanup_after_days: int = Form(90),
) -> HTMLResponse:
    svc = _service(request, "feature_flag_service", "feature flag service")
    try:
        state_enum = FlagState(state)
    except ValueError:
        state_enum = FlagState.ACTIVE
    await svc.upsert(
        project_id=project_id, name=name, owner=owner,
        description=description, state=state_enum,
        rollout_percent=rollout_percent,
        cleanup_after_days=cleanup_after_days,
    )
    return await project_flags(request, project_id)


@router.post(
    "/projects/{project_id}/release/flags/{name}/archive",
    response_class=HTMLResponse,
)
async def project_archive_flag(
    request: Request, project_id: str, name: str,
) -> HTMLResponse:
    svc = _service(request, "feature_flag_service", "feature flag service")
    try:
        await svc.archive(project_id, name)
    except ValueError:
        raise HTTPException(status_code=404, detail="flag not found")
    return await project_flags(request, project_id)


# ── Rollback actions ───────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/release/rollbacks", response_class=HTMLResponse,
)
async def project_rollbacks(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "rollback_action_service", "rollback service")
    actions = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "release_rollbacks_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "actions": actions,
        },
    )


@router.post(
    "/projects/{project_id}/release/rollbacks", response_class=HTMLResponse,
)
async def project_arm_rollback(
    request: Request,
    project_id: str,
    release_version: str = Form(...),
    revert_ref: str = Form(...),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "rollback_action_service", "rollback service")
    await svc.arm(
        project_id=project_id, release_version=release_version,
        revert_ref=revert_ref, note=note,
    )
    return await project_rollbacks(request, project_id)


@router.post(
    "/projects/{project_id}/release/rollbacks/{action_id}/execute",
    response_class=HTMLResponse,
)
async def project_execute_rollback(
    request: Request, project_id: str, action_id: str,
) -> HTMLResponse:
    svc = _service(request, "rollback_action_service", "rollback service")
    try:
        await svc.execute(action_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="action not found")
    return await project_rollbacks(request, project_id)


@router.post(
    "/projects/{project_id}/release/rollbacks/{action_id}/obsolete",
    response_class=HTMLResponse,
)
async def project_obsolete_rollback(
    request: Request, project_id: str, action_id: str,
) -> HTMLResponse:
    svc = _service(request, "rollback_action_service", "rollback service")
    try:
        await svc.mark_obsolete(action_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="action not found")
    return await project_rollbacks(request, project_id)
