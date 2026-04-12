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
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "dashboard": dto},
    )
