"""Chief of Staff dashboard routes (Phase K).

Portfolio-wide: routing rules, budget policies, archive list.
Project-scoped: onboarding wizard, per-project budget policy.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.chief_of_staff.value_objects import (
    ArchiveReason,
    BudgetState,
    OnboardingStatus,
    RuleStatus,
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


# ── Routing rules (portfolio-wide) ─────────────────────────────────


@router.get("/chief-of-staff/routing", response_class=HTMLResponse)
async def routing_list(request: Request) -> HTMLResponse:
    svc = _service(request, "routing_service", "routing service")
    rules = await svc.list()
    return _templates(request).TemplateResponse(
        "chief_of_staff_routing_fragment.html",
        {
            "request": request,
            "rules": rules,
            "statuses": list(RuleStatus),
        },
    )


@router.post("/chief-of-staff/routing", response_class=HTMLResponse)
async def routing_upsert(
    request: Request,
    pattern: str = Form(...),
    target_role: str = Form(...),
    target_codename: str = Form(""),
    priority: int = Form(100),
    status: str = Form("active"),
) -> HTMLResponse:
    svc = _service(request, "routing_service", "routing service")
    try:
        status_enum = RuleStatus(status)
    except ValueError:
        status_enum = RuleStatus.ACTIVE
    await svc.upsert(
        pattern=pattern, target_role=target_role,
        target_codename=target_codename, priority=priority,
        status=status_enum,
    )
    return await routing_list(request)


@router.post(
    "/chief-of-staff/routing/disable", response_class=HTMLResponse,
)
async def routing_disable(
    request: Request, pattern: str = Form(...),
) -> HTMLResponse:
    svc = _service(request, "routing_service", "routing service")
    try:
        await svc.disable(pattern)
    except ValueError:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    return await routing_list(request)


# ── Budget policies (portfolio + per-project) ──────────────────────


@router.get("/chief-of-staff/budgets", response_class=HTMLResponse)
async def budgets_list(request: Request) -> HTMLResponse:
    svc = _service(request, "budget_policy_service", "budget policy service")
    policies = await svc.list()
    return _templates(request).TemplateResponse(
        "chief_of_staff_budgets_fragment.html",
        {
            "request": request,
            "policies": policies,
            "states": list(BudgetState),
            "scope_label": "portfolio",
            "project_id": "",
        },
    )


@router.post("/chief-of-staff/budgets", response_class=HTMLResponse)
async def budgets_upsert(
    request: Request,
    project_id: str = Form(""),
    daily_tokens_limit: int = Form(0),
    daily_cost_usd_limit: float = Form(0.0),
    state: str = Form("active"),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "budget_policy_service", "budget policy service")
    try:
        state_enum = BudgetState(state)
    except ValueError:
        state_enum = BudgetState.ACTIVE
    await svc.upsert(
        project_id=project_id,
        daily_tokens_limit=daily_tokens_limit,
        daily_cost_usd_limit=daily_cost_usd_limit,
        state=state_enum, note=note,
    )
    return await budgets_list(request)


@router.post(
    "/chief-of-staff/budgets/state", response_class=HTMLResponse,
)
async def budgets_set_state(
    request: Request,
    project_id: str = Form(""),
    state: str = Form("active"),
) -> HTMLResponse:
    svc = _service(request, "budget_policy_service", "budget policy service")
    try:
        state_enum = BudgetState(state)
    except ValueError:
        state_enum = BudgetState.ACTIVE
    try:
        await svc.set_state(project_id, state_enum)
    except ValueError:
        raise HTTPException(status_code=404, detail="Budget policy not found")
    return await budgets_list(request)


# ── Onboarding (per-project wizard) ────────────────────────────────


@router.get(
    "/projects/{project_id}/chief-of-staff/onboarding",
    response_class=HTMLResponse,
)
async def onboarding_list(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "onboarding_service", "onboarding service")
    steps = await svc.list(project_id)
    done, total = await svc.progress(project_id)
    return _templates(request).TemplateResponse(
        "chief_of_staff_onboarding_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "steps": steps,
            "statuses": list(OnboardingStatus),
            "done": done,
            "total": total,
        },
    )


@router.post(
    "/projects/{project_id}/chief-of-staff/onboarding/seed",
    response_class=HTMLResponse,
)
async def onboarding_seed(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "onboarding_service", "onboarding service")
    await svc.seed_defaults(project_id)
    return await onboarding_list(request, project_id)


@router.post(
    "/projects/{project_id}/chief-of-staff/onboarding/{step_name}/status",
    response_class=HTMLResponse,
)
async def onboarding_set_status(
    request: Request, project_id: str, step_name: str,
    status: str = Form(...),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "onboarding_service", "onboarding service")
    try:
        status_enum = OnboardingStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="unknown status")
    try:
        await svc.mark_status(project_id, step_name, status_enum, note=note)
    except ValueError:
        raise HTTPException(status_code=404, detail="Onboarding step not found")
    return await onboarding_list(request, project_id)


# ── Archive (portfolio-wide log) ───────────────────────────────────


@router.get("/chief-of-staff/archive", response_class=HTMLResponse)
async def archive_list(request: Request) -> HTMLResponse:
    svc = _service(request, "archive_service", "archive service")
    archives = await svc.list()
    return _templates(request).TemplateResponse(
        "chief_of_staff_archive_fragment.html",
        {
            "request": request,
            "archives": archives,
            "reasons": list(ArchiveReason),
        },
    )


@router.post("/chief-of-staff/archive", response_class=HTMLResponse)
async def archive_project(
    request: Request,
    project_id: str = Form(...),
    reason: str = Form("other"),
    memory_frozen: str = Form("1"),
    export_path: str = Form(""),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "archive_service", "archive service")
    try:
        reason_enum = ArchiveReason(reason)
    except ValueError:
        reason_enum = ArchiveReason.OTHER
    await svc.archive(
        project_id=project_id, reason=reason_enum,
        memory_frozen=memory_frozen in ("1", "true", "on"),
        export_path=export_path, note=note,
    )
    return await archive_list(request)
