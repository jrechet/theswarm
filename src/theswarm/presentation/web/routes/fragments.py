"""Fragment routes: HTMX-swappable HTML partials for live dashboard updates."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery

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
