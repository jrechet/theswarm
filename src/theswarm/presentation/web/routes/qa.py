"""QA-enrichment dashboard routes (Phase F).

Surfaces test archetype mix, flake scoreboard, quarantine list, quality
gate snapshot, and demo outcome cards per project.

- ``GET  /projects/{pid}/qa/plans`` — test archetype mix fragment.
- ``POST /projects/{pid}/qa/plans`` — set required archetypes for a task.
- ``POST /projects/{pid}/qa/plans/{task_id}/produced`` — mark one archetype produced.
- ``GET  /projects/{pid}/qa/flakes`` — flake scoreboard fragment.
- ``POST /projects/{pid}/qa/flakes`` — record a test run result.
- ``GET  /projects/{pid}/qa/quarantine`` — quarantine list fragment.
- ``POST /projects/{pid}/qa/quarantine`` — quarantine a test.
- ``POST /projects/{pid}/qa/quarantine/{entry_id}/release`` — release from quarantine.
- ``GET  /projects/{pid}/qa/gates`` — quality gate snapshot fragment.
- ``POST /projects/{pid}/qa/gates`` — record a gate result.
- ``GET  /projects/{pid}/qa/outcomes`` — outcome cards fragment.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.qa.value_objects import (
    GateName,
    GateStatus,
    TestArchetype,
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


def _parse_archetypes(raw: str) -> tuple[TestArchetype, ...]:
    result: list[TestArchetype] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            result.append(TestArchetype(token))
        except ValueError:
            continue
    return tuple(result)


# ── Test archetype mix ─────────────────────────────────────────────


@router.get("/projects/{project_id}/qa/plans", response_class=HTMLResponse)
async def project_qa_plans(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "archetype_mix_service", "archetype-mix service")
    plans = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "qa_plans_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "plans": plans,
            "archetypes": list(TestArchetype),
        },
    )


@router.post("/projects/{project_id}/qa/plans", response_class=HTMLResponse)
async def project_qa_set_plan(
    request: Request,
    project_id: str,
    task_id: str = Form(...),
    required: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "archetype_mix_service", "archetype-mix service")
    await svc.set_required(
        project_id=project_id,
        task_id=task_id,
        required=_parse_archetypes(required),
        notes=notes,
    )
    return await project_qa_plans(request, project_id)


@router.post(
    "/projects/{project_id}/qa/plans/{task_id}/produced",
    response_class=HTMLResponse,
)
async def project_qa_mark_produced(
    request: Request,
    project_id: str,
    task_id: str,
    archetype: str = Form(...),
) -> HTMLResponse:
    svc = _service(request, "archetype_mix_service", "archetype-mix service")
    try:
        arch = TestArchetype(archetype)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="unknown archetype") from exc
    await svc.mark_produced(project_id=project_id, task_id=task_id, archetype=arch)
    return await project_qa_plans(request, project_id)


# ── Flake scoreboard ───────────────────────────────────────────────


@router.get("/projects/{project_id}/qa/flakes", response_class=HTMLResponse)
async def project_qa_flakes(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "flake_tracker_service", "flake-tracker service")
    records = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "qa_flakes_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "records": records,
        },
    )


@router.post("/projects/{project_id}/qa/flakes", response_class=HTMLResponse)
async def project_qa_record_flake(
    request: Request,
    project_id: str,
    test_id: str = Form(...),
    failed: str = Form("false"),
    failure_reason: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "flake_tracker_service", "flake-tracker service")
    did_fail = failed.lower() in {"true", "1", "on", "yes"}
    await svc.record_run(
        project_id=project_id,
        test_id=test_id,
        failed=did_fail,
        failure_reason=failure_reason,
    )
    return await project_qa_flakes(request, project_id)


# ── Quarantine list ────────────────────────────────────────────────


@router.get("/projects/{project_id}/qa/quarantine", response_class=HTMLResponse)
async def project_qa_quarantine(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "quarantine_service", "quarantine service")
    active = await svc.list_active(project_id)
    all_entries = await svc.list_all(project_id)
    return _templates(request).TemplateResponse(
        "qa_quarantine_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "active": active,
            "history": [e for e in all_entries if e.status.value == "released"],
        },
    )


@router.post("/projects/{project_id}/qa/quarantine", response_class=HTMLResponse)
async def project_qa_quarantine_add(
    request: Request,
    project_id: str,
    test_id: str = Form(...),
    reason: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "quarantine_service", "quarantine service")
    await svc.quarantine(project_id=project_id, test_id=test_id, reason=reason)
    return await project_qa_quarantine(request, project_id)


@router.post(
    "/projects/{project_id}/qa/quarantine/{entry_id}/release",
    response_class=HTMLResponse,
)
async def project_qa_quarantine_release(
    request: Request,
    project_id: str,
    entry_id: str,
    reason: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "quarantine_service", "quarantine service")
    await svc.release(entry_id=entry_id, reason=reason)
    return await project_qa_quarantine(request, project_id)


# ── Quality gates ──────────────────────────────────────────────────


@router.get("/projects/{project_id}/qa/gates", response_class=HTMLResponse)
async def project_qa_gates(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "quality_gate_service", "quality-gate service")
    snapshot = await svc.latest_snapshot(project_id)
    history = await svc.list(project_id, limit=20)
    gates_ordered = [(g, snapshot.get(g)) for g in GateName]
    return _templates(request).TemplateResponse(
        "qa_gates_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "gates": gates_ordered,
            "history": history,
            "gate_names": list(GateName),
            "gate_statuses": list(GateStatus),
        },
    )


@router.post("/projects/{project_id}/qa/gates", response_class=HTMLResponse)
async def project_qa_record_gate(
    request: Request,
    project_id: str,
    gate: str = Form(...),
    status: str = Form("unknown"),
    summary: str = Form(""),
    pr_url: str = Form(""),
    task_id: str = Form(""),
    finding_count: int = Form(0),
    score: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "quality_gate_service", "quality-gate service")
    try:
        gate_enum = GateName(gate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="unknown gate") from exc
    try:
        status_enum = GateStatus(status)
    except ValueError:
        status_enum = GateStatus.UNKNOWN
    score_val: float | None
    try:
        score_val = float(score) if score.strip() else None
    except ValueError:
        score_val = None
    await svc.record(
        project_id=project_id,
        gate=gate_enum,
        status=status_enum,
        summary=summary,
        pr_url=pr_url,
        task_id=task_id,
        finding_count=finding_count,
        score=score_val,
    )
    return await project_qa_gates(request, project_id)


# ── Outcome cards ──────────────────────────────────────────────────


@router.get("/projects/{project_id}/qa/outcomes", response_class=HTMLResponse)
async def project_qa_outcomes(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "outcome_card_service", "outcome-card service")
    cards = await svc.list(project_id, limit=20)
    return _templates(request).TemplateResponse(
        "qa_outcomes_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "cards": cards,
        },
    )
