"""Cycle routes: list, trigger, view status."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.commands.run_cycle import RunCycleCommand, RunCycleHandler
from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.list_cycles import ListCyclesQuery

router = APIRouter(prefix="/cycles")


@router.get("/", response_class=HTMLResponse)
async def list_cycles(request: Request, project_id: str = "") -> HTMLResponse:
    query: ListCyclesQuery = request.app.state.list_cycles_query
    cycles = await query.execute(project_id) if project_id else []
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "cycles_list.html",
        {"request": request, "cycles": cycles, "project_id": project_id},
    )


@router.get("/{cycle_id}", response_class=HTMLResponse)
async def cycle_detail(request: Request, cycle_id: str) -> HTMLResponse:
    query: GetCycleStatusQuery = request.app.state.get_cycle_status_query
    cycle = await query.execute(cycle_id)
    if cycle is None:
        return HTMLResponse("Cycle not found", status_code=404)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "cycles_detail.html",
        {"request": request, "cycle": cycle},
    )


@router.post("/trigger", response_class=RedirectResponse)
async def trigger_cycle(
    request: Request,
    project_id: str = Form(...),
) -> RedirectResponse:
    handler: RunCycleHandler = request.app.state.run_cycle_handler
    cycle_id = await handler.handle(
        RunCycleCommand(project_id=project_id, triggered_by="web"),
    )
    base = request.app.state.base_path
    return RedirectResponse(url=f"{base}/cycles/{cycle_id}", status_code=303)
