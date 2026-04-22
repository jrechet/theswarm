"""PO intelligence dashboard routes (Phase C).

- ``GET  /projects/{project_id}/proposals`` — HTMX fragment with inbox.
- ``POST /projects/{project_id}/proposals/{proposal_id}/decide`` — human decision.
- ``GET  /projects/{project_id}/okrs`` — OKR editor fragment.
- ``POST /projects/{project_id}/okrs`` — create OKR.
- ``POST /projects/{project_id}/okrs/{okr_id}/update`` — edit objective.
- ``POST /projects/{project_id}/okrs/{okr_id}/retire`` — retire OKR.
- ``GET  /projects/{project_id}/policy`` — policy editor fragment.
- ``POST /projects/{project_id}/policy`` — save policy.
- ``GET  /projects/{project_id}/digest`` — latest digest fragment.
- ``POST /projects/{project_id}/digest/generate`` — force generate now.
- ``GET  /projects/{project_id}/signals`` — recent signals fragment.
- ``GET  /proposals`` — portfolio inbox.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.domain.product.entities import KeyResult, OKR, Policy
from theswarm.domain.product.value_objects import ProposalStatus

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _proposal_repo(request: Request):
    return getattr(request.app.state, "proposal_repo", None)


def _okr_repo(request: Request):
    return getattr(request.app.state, "okr_repo", None)


def _policy_repo(request: Request):
    return getattr(request.app.state, "policy_repo", None)


def _signal_repo(request: Request):
    return getattr(request.app.state, "signal_repo", None)


def _digest_repo(request: Request):
    return getattr(request.app.state, "digest_repo", None)


def _proposal_service(request: Request):
    svc = getattr(request.app.state, "proposal_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="proposal service not configured")
    return svc


def _digest_service(request: Request):
    svc = getattr(request.app.state, "insight_digest_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="digest service not configured")
    return svc


# ── Proposals ────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/proposals", response_class=HTMLResponse)
async def project_proposals(request: Request, project_id: str) -> HTMLResponse:
    repo = _proposal_repo(request)
    inbox = await repo.list_inbox(project_id) if repo is not None else []
    decided = (
        await repo.list_for_project(
            project_id,
            statuses=(
                ProposalStatus.APPROVED,
                ProposalStatus.REJECTED,
                ProposalStatus.DEFERRED,
            ),
        )
        if repo is not None
        else []
    )
    counts = await repo.counts_by_status(project_id) if repo is not None else {}
    return _templates(request).TemplateResponse(
        "proposals_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "inbox": inbox,
            "decided": decided[:10],
            "counts": counts,
        },
    )


@router.post(
    "/projects/{project_id}/proposals/{proposal_id}/decide",
    response_class=HTMLResponse,
)
async def project_decide_proposal(
    request: Request,
    project_id: str,
    proposal_id: str,
    action: str = Form(...),
    note: str = Form(""),
) -> HTMLResponse:
    svc = _proposal_service(request)
    action_l = action.strip().lower()
    if action_l == "approve":
        await svc.approve(proposal_id, note=note)
    elif action_l == "reject":
        await svc.reject(proposal_id, note=note)
    elif action_l == "defer":
        await svc.defer(proposal_id, note=note)
    elif action_l == "ask":
        await svc.ask(proposal_id, note=note)
    else:
        raise HTTPException(status_code=400, detail=f"unknown action: {action}")
    # Re-render the fragment so HTMX can swap in place
    return await project_proposals(request, project_id)


@router.get("/proposals", response_class=HTMLResponse)
async def proposals_index(request: Request) -> HTMLResponse:
    """Portfolio-wide proposals inbox (across all projects)."""
    proj_repo = request.app.state.project_repo
    prop_repo = _proposal_repo(request)
    projects = await proj_repo.list_all()
    by_project: dict[str, list] = {}
    if prop_repo is not None:
        for p in projects:
            items = await prop_repo.list_inbox(p.id)
            if items:
                by_project[p.id] = items
    return _templates(request).TemplateResponse(
        "proposals_index.html",
        {
            "request": request,
            "projects": projects,
            "by_project": by_project,
        },
    )


# ── OKRs ─────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/okrs", response_class=HTMLResponse)
async def project_okrs(request: Request, project_id: str) -> HTMLResponse:
    repo = _okr_repo(request)
    okrs = await repo.list_for_project(project_id) if repo is not None else []
    return _templates(request).TemplateResponse(
        "okrs_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "okrs": okrs,
        },
    )


@router.post("/projects/{project_id}/okrs", response_class=HTMLResponse)
async def project_create_okr(
    request: Request,
    project_id: str,
    objective: str = Form(...),
    quarter: str = Form(""),
    owner_codename: str = Form(""),
    key_result_1: str = Form(""),
    key_result_2: str = Form(""),
    key_result_3: str = Form(""),
) -> HTMLResponse:
    repo = _okr_repo(request)
    if repo is None:
        raise HTTPException(status_code=503, detail="okr repo not configured")
    krs = tuple(
        KeyResult(id=KeyResult.new_id(), description=desc.strip())
        for desc in (key_result_1, key_result_2, key_result_3)
        if desc.strip()
    )
    okr = OKR(
        id=OKR.new_id(),
        project_id=project_id,
        objective=objective.strip(),
        quarter=quarter.strip(),
        owner_codename=owner_codename.strip(),
        key_results=krs,
    )
    await repo.create(okr)
    return await project_okrs(request, project_id)


@router.post(
    "/projects/{project_id}/okrs/{okr_id}/retire",
    response_class=HTMLResponse,
)
async def project_retire_okr(
    request: Request, project_id: str, okr_id: str,
) -> HTMLResponse:
    repo = _okr_repo(request)
    if repo is not None:
        await repo.retire(okr_id)
    return await project_okrs(request, project_id)


@router.post(
    "/projects/{project_id}/okrs/{okr_id}/key_results/{kr_id}",
    response_class=HTMLResponse,
)
async def project_update_kr(
    request: Request,
    project_id: str,
    okr_id: str,
    kr_id: str,
    current: str = Form(""),
    progress: float = Form(0.0),
) -> HTMLResponse:
    repo = _okr_repo(request)
    if repo is not None:
        await repo.update_key_result_progress(
            okr_id, kr_id, current=current, progress=max(0.0, min(1.0, progress)),
        )
    return await project_okrs(request, project_id)


# ── Policy ───────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/policy", response_class=HTMLResponse)
async def project_policy(request: Request, project_id: str) -> HTMLResponse:
    repo = _policy_repo(request)
    policy = await repo.get(project_id) if repo is not None else None
    return _templates(request).TemplateResponse(
        "policy_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "policy": policy,
        },
    )


@router.post("/projects/{project_id}/policy", response_class=HTMLResponse)
async def project_save_policy(
    request: Request,
    project_id: str,
    title: str = Form("Project policy"),
    body_markdown: str = Form(""),
    banned_terms: str = Form(""),
    require_review_terms: str = Form(""),
) -> HTMLResponse:
    repo = _policy_repo(request)
    if repo is None:
        raise HTTPException(status_code=503, detail="policy repo not configured")
    policy = Policy(
        id=Policy.new_id(),
        project_id=project_id,
        title=title.strip() or "Project policy",
        body_markdown=body_markdown,
        banned_terms=_split_terms(banned_terms),
        require_review_terms=_split_terms(require_review_terms),
        updated_by="human",
    )
    await repo.upsert(policy)
    return await project_policy(request, project_id)


def _split_terms(raw: str) -> tuple[str, ...]:
    return tuple(
        term.strip() for term in raw.replace("\n", ",").split(",")
        if term.strip()
    )


# ── Digest ───────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/digest", response_class=HTMLResponse)
async def project_digest(request: Request, project_id: str) -> HTMLResponse:
    repo = _digest_repo(request)
    digest = await repo.latest_for_project(project_id) if repo is not None else None
    return _templates(request).TemplateResponse(
        "digest_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "digest": digest,
        },
    )


@router.post(
    "/projects/{project_id}/digest/generate", response_class=HTMLResponse,
)
async def project_generate_digest(
    request: Request, project_id: str,
) -> HTMLResponse:
    svc = _digest_service(request)
    await svc.generate(project_id=project_id)
    return await project_digest(request, project_id)


# ── Signals ──────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/signals", response_class=HTMLResponse)
async def project_signals(request: Request, project_id: str) -> HTMLResponse:
    repo = _signal_repo(request)
    signals = await repo.list_for_project(project_id, limit=40) if repo is not None else []
    return _templates(request).TemplateResponse(
        "signals_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "signals": signals,
        },
    )
