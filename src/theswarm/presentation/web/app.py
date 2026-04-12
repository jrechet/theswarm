"""FastAPI app factory for the web dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from theswarm.application.commands.create_project import CreateProjectHandler
from theswarm.application.commands.delete_project import DeleteProjectHandler
from theswarm.application.commands.run_cycle import RunCycleHandler
from theswarm.application.events.bus import EventBus
from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.get_project import GetProjectQuery
from theswarm.application.queries.list_cycles import ListCyclesQuery
from theswarm.application.queries.list_projects import ListProjectsQuery
from theswarm.domain.cycles.ports import CycleRepository
from theswarm.domain.projects.ports import ProjectRepository
from theswarm.presentation.web.routes import api, cycles, dashboard, health, projects, reports, webhooks
from theswarm.presentation.web.sse import SSEHub

_HERE = Path(__file__).parent
_TEMPLATE_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"


class _TemplateEngine:
    """Thin wrapper matching Starlette's Jinja2Templates interface."""

    def __init__(self, directory: str | Path) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(directory)),
            autoescape=True,
        )

    def TemplateResponse(
        self, name: str, context: dict, status_code: int = 200,
    ) -> "HTMLResponse":
        from fastapi.responses import HTMLResponse
        template = self._env.get_template(name)
        html = template.render(**context)
        return HTMLResponse(content=html, status_code=status_code)


def create_web_app(
    project_repo: ProjectRepository,
    cycle_repo: CycleRepository,
    event_bus: EventBus,
    sse_hub: SSEHub | None = None,
) -> FastAPI:
    """Wire the web dashboard with dependency injection."""
    app = FastAPI(title="TheSwarm Dashboard", docs_url=None, redoc_url=None)

    # SSE hub
    hub = sse_hub or SSEHub()
    event_bus.subscribe_all(hub.broadcast)

    # Templates
    templates = _TemplateEngine(_TEMPLATE_DIR)

    # Inject dependencies into app.state
    app.state.templates = templates
    app.state.sse_hub = hub
    app.state.project_repo = project_repo

    # Queries
    app.state.list_projects_query = ListProjectsQuery(project_repo)
    app.state.get_project_query = GetProjectQuery(project_repo)
    app.state.get_cycle_status_query = GetCycleStatusQuery(cycle_repo)
    app.state.list_cycles_query = ListCyclesQuery(cycle_repo)
    app.state.get_dashboard_query = GetDashboardQuery(project_repo, cycle_repo)

    # Command handlers
    app.state.create_project_handler = CreateProjectHandler(project_repo)
    app.state.delete_project_handler = DeleteProjectHandler(project_repo)
    app.state.run_cycle_handler = RunCycleHandler(project_repo, cycle_repo, event_bus)

    # Routes
    app.include_router(dashboard.router)
    app.include_router(projects.router)
    app.include_router(cycles.router)
    app.include_router(health.router)
    app.include_router(reports.router)
    app.include_router(webhooks.router)
    app.include_router(api.router)

    # Static files
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app
