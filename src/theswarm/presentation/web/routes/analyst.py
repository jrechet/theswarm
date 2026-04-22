"""Analyst dashboard routes (Phase J).

Surfaces metric definitions, instrumentation plans, and outcome observations
per project.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.analyst.value_objects import (
    InstrumentationStatus,
    MetricKind,
    OutcomeDirection,
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


# ── Metric definitions ─────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/analyst/metrics", response_class=HTMLResponse,
)
async def project_metrics(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "metric_definition_service", "metric service")
    metrics = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "analyst_metrics_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "metrics": metrics,
            "kinds": list(MetricKind),
        },
    )


@router.post(
    "/projects/{project_id}/analyst/metrics", response_class=HTMLResponse,
)
async def project_upsert_metric(
    request: Request,
    project_id: str,
    name: str = Form(...),
    kind: str = Form("counter"),
    unit: str = Form(""),
    definition: str = Form(""),
    owner: str = Form(""),
    target: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "metric_definition_service", "metric service")
    try:
        kind_enum = MetricKind(kind)
    except ValueError:
        kind_enum = MetricKind.COUNTER
    await svc.upsert(
        project_id=project_id, name=name, kind=kind_enum,
        unit=unit, definition=definition, owner=owner, target=target,
    )
    return await project_metrics(request, project_id)


# ── Instrumentation plans ──────────────────────────────────────────


@router.get(
    "/projects/{project_id}/analyst/instrumentation",
    response_class=HTMLResponse,
)
async def project_instrumentation(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(
        request, "instrumentation_plan_service", "instrumentation service",
    )
    plans = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "analyst_instrumentation_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "plans": plans,
            "statuses": list(InstrumentationStatus),
        },
    )


@router.post(
    "/projects/{project_id}/analyst/instrumentation",
    response_class=HTMLResponse,
)
async def project_upsert_instrumentation(
    request: Request,
    project_id: str,
    story_id: str = Form(...),
    metric_name: str = Form(...),
    hypothesis: str = Form(""),
    method: str = Form(""),
    status: str = Form("proposed"),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "instrumentation_plan_service", "instrumentation service",
    )
    try:
        status_enum = InstrumentationStatus(status)
    except ValueError:
        status_enum = InstrumentationStatus.PROPOSED
    await svc.upsert(
        project_id=project_id, story_id=story_id, metric_name=metric_name,
        hypothesis=hypothesis, method=method,
        status=status_enum, note=note,
    )
    return await project_instrumentation(request, project_id)


@router.post(
    "/projects/{project_id}/analyst/instrumentation/{story_id}/{metric_name}/status",
    response_class=HTMLResponse,
)
async def project_mark_instrumentation_status(
    request: Request,
    project_id: str,
    story_id: str,
    metric_name: str,
    status: str = Form(...),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "instrumentation_plan_service", "instrumentation service",
    )
    try:
        status_enum = InstrumentationStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="unknown status")
    await svc.mark_status(
        project_id, story_id, metric_name,
        status=status_enum, note=note,
    )
    return await project_instrumentation(request, project_id)


# ── Outcome observations ───────────────────────────────────────────


@router.get(
    "/projects/{project_id}/analyst/outcomes", response_class=HTMLResponse,
)
async def project_outcomes(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "outcome_observation_service", "outcome service")
    outcomes = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "analyst_outcomes_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "outcomes": outcomes,
            "directions": list(OutcomeDirection),
        },
    )


@router.post(
    "/projects/{project_id}/analyst/outcomes", response_class=HTMLResponse,
)
async def project_record_outcome(
    request: Request,
    project_id: str,
    story_id: str = Form(...),
    metric_name: str = Form(...),
    baseline: str = Form(""),
    observed: str = Form(""),
    direction: str = Form("inconclusive"),
    window: str = Form(""),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "outcome_observation_service", "outcome service")
    try:
        dir_enum = OutcomeDirection(direction)
    except ValueError:
        dir_enum = OutcomeDirection.INCONCLUSIVE
    await svc.record(
        project_id=project_id, story_id=story_id, metric_name=metric_name,
        baseline=baseline, observed=observed, direction=dir_enum,
        window=window, note=note,
    )
    return await project_outcomes(request, project_id)
