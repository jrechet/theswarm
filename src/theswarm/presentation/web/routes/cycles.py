"""Cycle routes: list, trigger, view status."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.queries.get_cycle_replay import GetCycleReplayQuery
from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.list_cycles import ListCyclesQuery

log = logging.getLogger(__name__)

router = APIRouter(prefix="/cycles")


@router.get("/", response_class=HTMLResponse)
async def list_cycles(request: Request, project_id: str = "") -> HTMLResponse:
    query: ListCyclesQuery = request.app.state.list_cycles_query
    cycles = list(await query.execute(project_id) if project_id else [])

    # Merge in-memory tracker records (web/API-triggered)
    from theswarm.api import get_cycle_tracker
    tracker = get_cycle_tracker()
    tracker_records = tracker.list_recent(limit=20)
    tracker_ids = {r.id for r in tracker_records}
    existing_ids = {c.id for c in cycles}
    for record in tracker_records:
        if record.id not in existing_ids:
            if not project_id or record.repo == project_id:
                cycles.append(_tracker_record_to_dto(record))

    templates = request.app.state.templates
    # Return fragment for HTMX requests (e.g. project detail page)
    is_htmx = request.headers.get("hx-request") == "true"
    template = "cycles_fragment.html" if is_htmx else "cycles_list.html"
    return templates.TemplateResponse(
        template,
        {"request": request, "cycles": cycles, "project_id": project_id},
    )


@router.get("/{cycle_id}/live", response_class=HTMLResponse)
async def cycle_live_preview(request: Request, cycle_id: str) -> HTMLResponse:
    """Render a live-preview iframe for a running cycle's PR branch."""
    templates = request.app.state.templates
    query: GetCycleStatusQuery = request.app.state.get_cycle_status_query
    project_repo = getattr(request.app.state, "project_repo", None)

    cycle = await query.execute(cycle_id)
    project = None
    if cycle is not None and project_repo is not None:
        project = await project_repo.get(cycle.project_id)

    template_str = ""
    if project is not None:
        template_str = project.config.preview_url_template or ""

    pr_number = ""
    branch = ""
    if cycle is not None and cycle.prs_opened:
        pr_number = str(cycle.prs_opened[0])
        branch = f"pr-{pr_number}"

    preview_url = ""
    if template_str and pr_number:
        preview_url = (
            template_str
            .replace("{pr}", pr_number)
            .replace("{branch}", branch)
            .replace("{cycle_id}", cycle_id)
        )

    return templates.TemplateResponse(
        "cycle_live.html",
        {
            "request": request,
            "cycle": cycle,
            "cycle_id": cycle_id,
            "preview_url": preview_url,
            "template_configured": bool(template_str),
            "project": project,
        },
    )


@router.get("/{cycle_id}/replay", response_class=HTMLResponse)
async def cycle_replay(request: Request, cycle_id: str) -> HTMLResponse:
    """Render the cycle replay scrubber page."""
    templates = request.app.state.templates
    replay_query: GetCycleReplayQuery = request.app.state.get_cycle_replay_query
    status_query: GetCycleStatusQuery = request.app.state.get_cycle_status_query

    cycle = await status_query.execute(cycle_id)
    frames = await replay_query.execute(cycle_id)

    frames_json = [
        {
            "index": f.index,
            "event_type": f.event_type,
            "occurred_at": f.occurred_at.isoformat(),
            "offset_ms": f.offset_ms,
            "payload": f.payload,
        }
        for f in frames
    ]
    total_ms = frames_json[-1]["offset_ms"] if frames_json else 0

    return templates.TemplateResponse(
        "cycle_replay.html",
        {
            "request": request,
            "cycle": cycle,
            "cycle_id": cycle_id,
            "frames": frames_json,
            "frame_count": len(frames_json),
            "total_ms": total_ms,
        },
    )


@router.get("/{cycle_id}/replay.json")
async def cycle_replay_json(request: Request, cycle_id: str) -> dict:
    """JSON replay frames for client-side playback."""
    replay_query: GetCycleReplayQuery = request.app.state.get_cycle_replay_query
    frames = await replay_query.execute(cycle_id)
    return {
        "cycle_id": cycle_id,
        "frames": [
            {
                "index": f.index,
                "event_type": f.event_type,
                "occurred_at": f.occurred_at.isoformat(),
                "offset_ms": f.offset_ms,
                "payload": f.payload,
            }
            for f in frames
        ],
    }


@router.get("/{cycle_id}", response_class=HTMLResponse)
async def cycle_detail(request: Request, cycle_id: str) -> HTMLResponse:
    # Check v2 SQLite first
    query: GetCycleStatusQuery = request.app.state.get_cycle_status_query
    cycle = await query.execute(cycle_id)

    if cycle is not None:
        templates = request.app.state.templates
        return templates.TemplateResponse(
            "cycles_detail.html",
            {"request": request, "cycle": cycle},
        )

    # Fall back to in-memory tracker (for web/API-triggered cycles)
    from theswarm.api import get_cycle_tracker
    tracker = get_cycle_tracker()
    record = tracker.get(cycle_id)
    if record is None:
        return HTMLResponse("Cycle not found", status_code=404)

    # Adapt tracker record to template-compatible dict
    tracker_cycle = _tracker_record_to_dto(record)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "cycles_detail.html",
        {"request": request, "cycle": tracker_cycle},
    )


def _tracker_record_to_dto(record):
    """Convert an in-memory CycleRecord to a template-compatible object."""
    from types import SimpleNamespace
    return SimpleNamespace(
        id=record.id,
        project_id=record.repo,
        status=record.status.value,
        triggered_by="web",
        started_at=record.started_at or "",
        completed_at=record.completed_at or "",
        total_tokens=record.result.get("total_tokens", 0) if record.result else 0,
        total_cost_usd=record.result.get("cost_usd", 0.0) if record.result else 0.0,
        prs_opened=record.result.get("prs_opened", []) if record.result else [],
        prs_merged=record.result.get("prs_merged", []) if record.result else [],
        phases=_extract_phases(record),
    )


def _extract_phases(record):
    """Extract phase info from a tracker record's result."""
    from types import SimpleNamespace
    if not record.result:
        if record.error:
            return [SimpleNamespace(
                agent="system", phase="error", status="failed",
                summary=record.error, tokens_used=0, cost_usd=0.0,
            )]
        return []
    phases = []
    for agent_result in record.result.get("agents", []):
        phases.append(SimpleNamespace(
            agent=agent_result.get("role", "unknown"),
            phase=agent_result.get("phase", ""),
            status=agent_result.get("status", "completed"),
            summary=agent_result.get("summary", ""),
            tokens_used=agent_result.get("tokens", 0),
            cost_usd=agent_result.get("cost_usd", 0.0),
        ))
    return phases


@router.post("/trigger", response_class=RedirectResponse)
async def trigger_cycle(
    request: Request,
    project_id: str = Form(...),
) -> RedirectResponse:
    from theswarm.application.queries.get_project import GetProjectQuery
    from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle

    # Look up project to get repo URL
    get_project: GetProjectQuery = request.app.state.get_project_query
    project = await get_project.execute(project_id)
    if project is None:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(f"Project not found: {project_id}", status_code=404)

    repo = str(project.repo)

    # Use headless API tracker (source of truth for running cycles)
    tracker = get_cycle_tracker()
    req = CycleRequest(repo=repo, description=f"Web-triggered cycle for {project_id}")
    record = tracker.create(req)

    allowed_repos = getattr(request.app.state, "allowed_repos", [])
    event_bus = getattr(request.app.state, "event_bus", None)
    report_repo = getattr(request.app.state, "report_repo", None)
    base_path = getattr(request.app.state, "base_path", "")
    task = asyncio.create_task(
        run_api_cycle(
            record.id, repo, req.description, "", allowed_repos,
            event_bus=event_bus, report_repo=report_repo, base_path=base_path,
        )
    )
    tracker.set_task(record.id, task)
    log.info("Cycle %s triggered for project %s (repo=%s)", record.id, project_id, repo)

    base = request.app.state.base_path
    return RedirectResponse(url=f"{base}/cycles/{record.id}", status_code=303)
