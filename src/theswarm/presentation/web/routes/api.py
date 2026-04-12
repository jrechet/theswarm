"""REST API routes for external consumers and HTMX partials."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.list_projects import ListProjectsQuery
from theswarm.presentation.web.sse import SSEHub

router = APIRouter(prefix="/api")


@router.get("/projects")
async def api_projects(request: Request) -> JSONResponse:
    query: ListProjectsQuery = request.app.state.list_projects_query
    projects = await query.execute()
    return JSONResponse([
        {
            "id": p.id,
            "repo": p.repo,
            "framework": p.framework,
            "ticket_source": p.ticket_source,
        }
        for p in projects
    ])


@router.get("/dashboard")
async def api_dashboard(request: Request) -> JSONResponse:
    query: GetDashboardQuery = request.app.state.get_dashboard_query
    dto = await query.execute()
    return JSONResponse({
        "active_cycles": len(dto.active_cycles),
        "projects": len(dto.projects),
        "total_cost_today": dto.total_cost_today,
    })


@router.get("/cycles/{cycle_id}")
async def api_cycle(request: Request, cycle_id: str) -> JSONResponse:
    query: GetCycleStatusQuery = request.app.state.get_cycle_status_query
    cycle = await query.execute(cycle_id)
    if cycle is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "id": cycle.id,
        "project_id": cycle.project_id,
        "status": cycle.status,
        "triggered_by": cycle.triggered_by,
        "total_cost_usd": cycle.total_cost_usd,
        "phases": len(cycle.phases),
    })


@router.get("/events")
async def sse_stream(request: Request) -> StreamingResponse:
    """SSE endpoint for real-time updates."""
    hub: SSEHub = request.app.state.sse_hub
    queue = hub.connect()
    return StreamingResponse(
        hub.event_stream(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
