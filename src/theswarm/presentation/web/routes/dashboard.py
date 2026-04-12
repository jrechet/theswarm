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
    for record in tracker.list_recent(limit=10):
        if record.status.value in ("queued", "running") and record.id not in existing_ids:
            dto.active_cycles.append(CycleDTO(
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

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "dashboard": dto},
    )
