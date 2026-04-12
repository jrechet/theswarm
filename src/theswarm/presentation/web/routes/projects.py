"""Project CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.commands.create_project import (
    CreateProjectCommand,
    CreateProjectHandler,
)
from theswarm.application.commands.delete_project import (
    DeleteProjectCommand,
    DeleteProjectHandler,
)
from theswarm.application.queries.get_project import GetProjectQuery
from theswarm.application.queries.list_projects import ListProjectsQuery

router = APIRouter(prefix="/projects")


@router.get("/", response_class=HTMLResponse)
async def list_projects(request: Request) -> HTMLResponse:
    query: ListProjectsQuery = request.app.state.list_projects_query
    projects = await query.execute()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects_list.html",
        {"request": request, "projects": projects},
    )


@router.get("/new", response_class=HTMLResponse)
async def create_form(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects_create.html",
        {"request": request},
    )


@router.post("/", response_class=RedirectResponse)
async def create_project(
    request: Request,
    project_id: str = Form(...),
    repo: str = Form(...),
    framework: str = Form("auto"),
    ticket_source: str = Form("github"),
    team_channel: str = Form(""),
) -> RedirectResponse:
    handler: CreateProjectHandler = request.app.state.create_project_handler
    await handler.handle(
        CreateProjectCommand(
            project_id=project_id,
            repo=repo,
            framework=framework,
            ticket_source=ticket_source,
            team_channel=team_channel,
        )
    )
    return RedirectResponse(url="/projects/", status_code=303)


@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str) -> HTMLResponse:
    query: GetProjectQuery = request.app.state.get_project_query
    project = await query.execute(project_id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "projects_detail.html",
        {"request": request, "project": project},
    )


@router.post("/{project_id}/delete", response_class=RedirectResponse)
async def delete_project(request: Request, project_id: str) -> RedirectResponse:
    handler: DeleteProjectHandler = request.app.state.delete_project_handler
    await handler.handle(DeleteProjectCommand(project_id=project_id))
    return RedirectResponse(url="/projects/", status_code=303)
