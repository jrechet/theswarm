"""Dashboard routes: live activity feed, project overview."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from theswarm.application.queries.get_dashboard import GetDashboardQuery

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    query: GetDashboardQuery = request.app.state.get_dashboard_query
    dto = await query.execute()

    # Merge in-memory tracker cycles (web/API-triggered)
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

    # Reconstruct DTO with merged active cycles
    from theswarm.application.dto import DashboardDTO
    dto = DashboardDTO(
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

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "dashboard": dto},
    )
