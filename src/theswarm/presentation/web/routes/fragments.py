"""Fragment routes: HTMX-swappable HTML partials for live dashboard updates."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery

log = logging.getLogger(__name__)

router = APIRouter(prefix="/fragments")


@router.get("/stats", response_class=HTMLResponse)
async def stats_fragment(request: Request) -> HTMLResponse:
    query: GetDashboardQuery = request.app.state.get_dashboard_query
    dto = await query.execute()
    # Merge in-memory tracker cycles
    dto = _merge_tracker_cycles(dto)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_stats_row.html", {"request": request, "dashboard": dto},
    )


@router.get("/active-cycles", response_class=HTMLResponse)
async def active_cycles_fragment(request: Request) -> HTMLResponse:
    query: GetDashboardQuery = request.app.state.get_dashboard_query
    dto = await query.execute()
    dto = _merge_tracker_cycles(dto)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_active_cycles.html", {"request": request, "dashboard": dto},
    )


@router.get("/recent-cycles", response_class=HTMLResponse)
async def recent_cycles_fragment(request: Request) -> HTMLResponse:
    query: GetDashboardQuery = request.app.state.get_dashboard_query
    dto = await query.execute()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_recent_cycles.html", {"request": request, "dashboard": dto},
    )


@router.get("/cycle/{cycle_id}/overview", response_class=HTMLResponse)
async def cycle_overview_fragment(request: Request, cycle_id: str) -> HTMLResponse:
    query: GetCycleStatusQuery = request.app.state.get_cycle_status_query
    cycle = await query.execute(cycle_id)
    if cycle is None:
        # Fall back to in-memory tracker
        from theswarm.presentation.web.routes.cycles import _tracker_record_to_dto
        from theswarm.api import get_cycle_tracker
        record = get_cycle_tracker().get(cycle_id)
        if record is None:
            return HTMLResponse("Cycle not found", status_code=404)
        cycle = _tracker_record_to_dto(record)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_cycle_overview.html", {"request": request, "cycle": cycle},
    )


@router.get("/cycle/{cycle_id}/timeline", response_class=HTMLResponse)
async def cycle_timeline_fragment(request: Request, cycle_id: str) -> HTMLResponse:
    query = getattr(request.app.state, "get_agent_timeline_query", None)
    rows: list = []
    if query is not None:
        rows = await query.execute(cycle_id)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_agent_timeline.html", {"request": request, "rows": rows},
    )


@router.get("/cycle/{cycle_id}/thoughts", response_class=HTMLResponse)
async def cycle_thoughts_fragment(request: Request, cycle_id: str) -> HTMLResponse:
    query = getattr(request.app.state, "get_agent_thoughts_query", None)
    entries: list = []
    if query is not None:
        entries = await query.execute(cycle_id)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_agent_thoughts.html",
        {"request": request, "entries": entries},
    )


@router.get("/cycle/{cycle_id}/phases", response_class=HTMLResponse)
async def cycle_phases_fragment(request: Request, cycle_id: str) -> HTMLResponse:
    query: GetCycleStatusQuery = request.app.state.get_cycle_status_query
    cycle = await query.execute(cycle_id)
    if cycle is None:
        from theswarm.presentation.web.routes.cycles import _tracker_record_to_dto
        from theswarm.api import get_cycle_tracker
        record = get_cycle_tracker().get(cycle_id)
        if record is None:
            return HTMLResponse("Cycle not found", status_code=404)
        cycle = _tracker_record_to_dto(record)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_cycle_phases.html", {"request": request, "cycle": cycle},
    )


@router.get("/cycle/{cycle_id}/live-progress", response_class=HTMLResponse)
async def cycle_live_progress_fragment(request: Request, cycle_id: str) -> HTMLResponse:
    """Live messages per role from the in-process ProgressBridge cache."""
    from theswarm.application.services.progress_bridge import get_live_progress

    rows = get_live_progress(cycle_id)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "partials/_cycle_live_progress.html",
        {"request": request, "rows": rows},
    )


@router.get("/cycle/{cycle_id}/issue", response_class=HTMLResponse)
async def cycle_issue_fragment(request: Request, cycle_id: str) -> HTMLResponse:
    """What a targeted cycle is building: the pinned issue and its breakdown.

    Issue-driven flow P3 (theswarm#25). The TechLead breakdown already
    creates sub-issues carrying ``Parent: #N``; this reads them back so the
    page answers 'the feature was split into X tasks, here is where each
    one stands' while the cycle runs.
    """
    from theswarm.api import get_cycle_tracker

    record = get_cycle_tracker().get(cycle_id)
    context: dict = {
        "request": request,
        "cycle_id": cycle_id,
        "issue": None,
        "children": [],
        "done": 0,
        "repo": "",
        "error": "",
    }

    if record is None or record.issue_number is None:
        # Untargeted (or DB-backed) cycle: nothing to pin, render nothing.
        return request.app.state.templates.TemplateResponse(
            "partials/_cycle_issue.html", context,
        )

    context["repo"] = record.repo
    try:
        from theswarm.tools.github import GitHubClient

        client = GitHubClient(record.repo)
        issue = await client.get_issue(record.issue_number)
        context["issue"] = issue
        if issue is not None:
            from theswarm.tools.github import issue_status

            marker = f"Parent: #{record.issue_number}"
            everything = await client.get_issues(state="all")
            children = [
                {
                    "number": child["number"],
                    "title": child["title"],
                    "status": issue_status(child),
                }
                for child in everything
                if marker in (child.get("body") or "")
            ]
            context["children"] = children
            context["done"] = sum(1 for c in children if c["status"] == "review")
    except Exception as exc:  # noqa: BLE001 — degrade the panel, not the page
        log.exception("Failed to read issue %s for cycle %s",
                      record.issue_number, cycle_id)
        context["error"] = str(exc)[:200]

    return request.app.state.templates.TemplateResponse(
        "partials/_cycle_issue.html", context,
    )


def _merge_tracker_cycles(dto):
    """Merge in-memory tracker cycles into the dashboard DTO."""
    from theswarm.api import get_cycle_tracker
    from theswarm.application.dto import CycleDTO

    tracker = get_cycle_tracker()
    existing_ids = {c.id for c in dto.active_cycles}
    new_active = list(dto.active_cycles)

    for record in tracker.list_recent(limit=10):
        if record.status.value in ("queued", "running") and record.id not in existing_ids:
            new_active.append(CycleDTO(
                id=record.id,
                project_id=record.repo,
                status=record.status.value,
                triggered_by="web",
                started_at=record.started_at or None,
                completed_at=None,
                total_tokens=0,
                total_cost_usd=0.0,
                prs_opened=[],
                prs_merged=[],
                phases=[],
            ))

    # Return a new DTO with merged active cycles
    return type(dto)(
        active_cycles=new_active,
        recent_cycles=dto.recent_cycles,
        recent_activities=dto.recent_activities,
        projects=dto.projects,
        total_cost_today=dto.total_cost_today,
        total_cost_week=dto.total_cost_week,
        success_rate_7d=dto.success_rate_7d,
        cycles_completed_7d=dto.cycles_completed_7d,
        cycles_failed_7d=dto.cycles_failed_7d,
    )
