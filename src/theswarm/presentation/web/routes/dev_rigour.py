"""Dev-rigour dashboard routes (Phase E).

Surfaces Dev exploration thoughts, TDD status, refactor preflight log,
self-reviews, and coverage deltas per project.

- ``GET  /projects/{pid}/dev/thoughts`` — thoughts stream fragment.
- ``POST /projects/{pid}/dev/thoughts`` — log a thought (manual or agent).
- ``GET  /projects/{pid}/dev/tdd`` — TDD artifact list fragment.
- ``POST /projects/{pid}/dev/tdd/red`` — record a RED artifact.
- ``POST /projects/{pid}/dev/tdd/{task_id}/green`` — promote to GREEN.
- ``GET  /projects/{pid}/dev/preflight`` — refactor preflight fragment.
- ``POST /projects/{pid}/dev/preflight`` — log a preflight check.
- ``GET  /projects/{pid}/dev/self-reviews`` — self-review fragment.
- ``GET  /projects/{pid}/dev/coverage`` — coverage-delta fragment.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.dev_rigour.value_objects import (
    PreflightDecision,
    ThoughtKind,
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


# ── Thoughts stream ──────────────────────────────────────────────


@router.get("/projects/{project_id}/dev/thoughts", response_class=HTMLResponse)
async def project_dev_thoughts(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "dev_thought_service", "dev-thought service")
    thoughts = await svc.recent(project_id, limit=30)
    return _templates(request).TemplateResponse(
        "dev_thoughts_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "thoughts": thoughts,
        },
    )


@router.post("/projects/{project_id}/dev/thoughts", response_class=HTMLResponse)
async def project_log_dev_thought(
    request: Request,
    project_id: str,
    content: str = Form(...),
    kind: str = Form("note"),
    task_id: str = Form(""),
    codename: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "dev_thought_service", "dev-thought service")
    try:
        kind_enum = ThoughtKind(kind)
    except ValueError:
        kind_enum = ThoughtKind.NOTE
    if content.strip():
        await svc.log(
            project_id=project_id,
            kind=kind_enum,
            content=content,
            task_id=task_id,
            codename=codename,
        )
    return await project_dev_thoughts(request, project_id)


# ── TDD artifacts ────────────────────────────────────────────────


@router.get("/projects/{project_id}/dev/tdd", response_class=HTMLResponse)
async def project_dev_tdd(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "tdd_gate_service", "tdd-gate service")
    artifacts = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "dev_tdd_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "artifacts": artifacts,
        },
    )


@router.post("/projects/{project_id}/dev/tdd/red", response_class=HTMLResponse)
async def project_dev_tdd_red(
    request: Request,
    project_id: str,
    task_id: str = Form(...),
    test_files: str = Form(""),
    commit: str = Form(""),
    codename: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "tdd_gate_service", "tdd-gate service")
    files = tuple(
        f.strip() for f in test_files.split(",") if f.strip()
    )
    await svc.record_red(
        project_id=project_id,
        task_id=task_id,
        test_files=files,
        commit=commit,
        codename=codename,
    )
    return await project_dev_tdd(request, project_id)


@router.post(
    "/projects/{project_id}/dev/tdd/{task_id}/green",
    response_class=HTMLResponse,
)
async def project_dev_tdd_green(
    request: Request,
    project_id: str,
    task_id: str,
    commit: str = Form(""),
) -> HTMLResponse:
    svc = _service(request, "tdd_gate_service", "tdd-gate service")
    await svc.record_green(
        project_id=project_id, task_id=task_id, commit=commit,
    )
    return await project_dev_tdd(request, project_id)


# ── Refactor preflight ───────────────────────────────────────────


@router.get("/projects/{project_id}/dev/preflight", response_class=HTMLResponse)
async def project_dev_preflight(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(
        request, "refactor_preflight_service", "refactor-preflight service",
    )
    entries = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "dev_preflight_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "entries": entries,
            "threshold": svc.threshold_lines,
        },
    )


@router.post("/projects/{project_id}/dev/preflight", response_class=HTMLResponse)
async def project_dev_log_preflight(
    request: Request,
    project_id: str,
    deletion_lines: int = Form(...),
    decision: str = Form("proceed"),
    reason: str = Form(""),
    files_touched: str = Form(""),
    callers_checked: str = Form(""),
    pr_url: str = Form(""),
    task_id: str = Form(""),
) -> HTMLResponse:
    svc = _service(
        request, "refactor_preflight_service", "refactor-preflight service",
    )
    try:
        decision_enum = PreflightDecision(decision)
    except ValueError:
        decision_enum = PreflightDecision.PROCEED
    files = tuple(f.strip() for f in files_touched.split(",") if f.strip())
    callers = tuple(c.strip() for c in callers_checked.split(",") if c.strip())
    await svc.evaluate(
        project_id=project_id,
        deletion_lines=deletion_lines,
        decision=decision_enum,
        reason=reason,
        files_touched=files,
        callers_checked=callers,
        pr_url=pr_url,
        task_id=task_id,
    )
    return await project_dev_preflight(request, project_id)


# ── Self-reviews ─────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/dev/self-reviews", response_class=HTMLResponse,
)
async def project_dev_self_reviews(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "self_review_service", "self-review service")
    reviews = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "dev_self_reviews_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "reviews": reviews,
        },
    )


# ── Coverage deltas ──────────────────────────────────────────────


@router.get("/projects/{project_id}/dev/coverage", response_class=HTMLResponse)
async def project_dev_coverage(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _service(request, "coverage_delta_service", "coverage-delta service")
    deltas = await svc.list(project_id)
    return _templates(request).TemplateResponse(
        "dev_coverage_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "deltas": deltas,
        },
    )
