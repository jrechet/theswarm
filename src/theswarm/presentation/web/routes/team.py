"""Roster / team pages: per-project tab + global portfolio view."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/team", response_class=HTMLResponse)
async def team_roster(request: Request) -> HTMLResponse:
    """Global roster across all projects + portfolio roles."""
    query = getattr(request.app.state, "list_role_assignments_query", None)
    entries = await query.all() if query is not None else []
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "team_roster.html",
        {"request": request, "entries": entries},
    )


@router.get("/projects/{project_id}/team", response_class=HTMLResponse)
async def project_team_fragment(
    request: Request, project_id: str,
) -> HTMLResponse:
    """HTMX fragment: roster card for a single project page."""
    query = getattr(request.app.state, "list_role_assignments_query", None)
    entries = await query.for_project(project_id) if query is not None else []
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "team_project_fragment.html",
        {"request": request, "project_id": project_id, "entries": entries},
    )
