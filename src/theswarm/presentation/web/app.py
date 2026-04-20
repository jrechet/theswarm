"""FastAPI app factory for the web dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from theswarm.application.commands.create_project import CreateProjectHandler
from theswarm.application.commands.delete_project import DeleteProjectHandler
from theswarm.application.commands.manage_schedule import (
    DeleteScheduleHandler,
    DisableScheduleHandler,
    SetScheduleHandler,
)
from theswarm.application.commands.run_cycle import RunCycleHandler
from theswarm.application.commands.update_project_config import (
    UpdateProjectConfigHandler,
)
from theswarm.application.events.bus import EventBus
from theswarm.application.queries.get_agent_thoughts import GetAgentThoughtsQuery
from theswarm.application.queries.get_agent_timeline import GetAgentTimelineQuery
from theswarm.application.queries.get_cycle_replay import GetCycleReplayQuery
from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.get_project import GetProjectQuery
from theswarm.application.queries.get_schedule import (
    GetScheduleQuery,
    ListEnabledSchedulesQuery,
)
from theswarm.application.queries.list_cycles import ListCyclesQuery
from theswarm.application.queries.list_project_memory import ListProjectMemoryQuery
from theswarm.application.queries.list_projects import ListProjectsQuery
from theswarm.domain.cycles.ports import CycleRepository
from theswarm.domain.projects.ports import ProjectRepository
from theswarm.domain.scheduling.ports import ScheduleRepository
from theswarm.application.events.cycle_event_persistence import (
    CycleEventPersistenceHandler,
)
from theswarm.application.events.persistence_handlers import (
    ActivityPersistenceHandler,
    CyclePersistenceHandler,
)
from theswarm.domain.cycles.events import (
    AgentActivity,
    AgentStep,
    AgentThought,
    BudgetExceeded,
    CycleCompleted,
    CycleFailed,
    CycleStarted,
    PhaseChanged,
)
from theswarm.presentation.web.routes import api, artifacts, cycles, dashboard, demos, features, fragments, health, metrics, projects, reports, webhooks
from theswarm.presentation.web.sse import SSEHub

_HERE = Path(__file__).parent
_TEMPLATE_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"


class _TemplateEngine:
    """Thin wrapper matching Starlette's Jinja2Templates interface."""

    def __init__(self, directory: str | Path, base_path: str = "") -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(directory)),
            autoescape=True,
        )
        self._base_path = base_path.rstrip("/")

    def TemplateResponse(
        self, name: str, context: dict, status_code: int = 200,
    ) -> "HTMLResponse":
        from fastapi.responses import HTMLResponse
        context.setdefault("base", self._base_path)
        template = self._env.get_template(name)
        html = template.render(**context)
        return HTMLResponse(content=html, status_code=status_code)


def create_web_app(
    project_repo: ProjectRepository,
    cycle_repo: CycleRepository,
    event_bus: EventBus,
    sse_hub: SSEHub | None = None,
    base_path: str = "",
    activity_repo: object | None = None,
    report_repo: object | None = None,
    artifact_store: object | None = None,
    schedule_repo: ScheduleRepository | None = None,
    secret_vault: object | None = None,
    db: object | None = None,
    vcs_factory: Callable[[str], object] | None = None,
    cycle_event_store: object | None = None,
    memory_store: object | None = None,
) -> FastAPI:
    """Wire the web dashboard with dependency injection."""
    app = FastAPI(title="TheSwarm Dashboard", docs_url=None, redoc_url=None)
    app.state.base_path = base_path.rstrip("/")

    # SSE hub
    hub = sse_hub or SSEHub()
    event_bus.subscribe_all(hub.broadcast)

    # Templates
    templates = _TemplateEngine(_TEMPLATE_DIR, base_path=base_path)

    # Inject dependencies into app.state
    app.state.templates = templates
    app.state.sse_hub = hub
    app.state.event_bus = event_bus
    app.state.project_repo = project_repo
    app.state.cycle_repo = cycle_repo

    # Queries
    app.state.list_projects_query = ListProjectsQuery(project_repo)
    app.state.get_project_query = GetProjectQuery(project_repo)
    app.state.get_cycle_status_query = GetCycleStatusQuery(cycle_repo)
    app.state.list_cycles_query = ListCyclesQuery(cycle_repo)
    app.state.get_dashboard_query = GetDashboardQuery(project_repo, cycle_repo, activity_repo)
    app.state.get_agent_timeline_query = GetAgentTimelineQuery(activity_repo)
    app.state.get_cycle_replay_query = GetCycleReplayQuery(cycle_event_store)
    app.state.get_agent_thoughts_query = GetAgentThoughtsQuery(cycle_event_store)

    # Sprint D C5 — cost estimator for the Run Cycle preview modal
    from theswarm.application.services.cost_estimator import CostEstimator
    app.state.cost_estimator = CostEstimator(cycle_repo)

    # Sprint E M1 — memory viewer
    app.state.memory_store = memory_store
    if memory_store is not None:
        app.state.list_project_memory_query = ListProjectMemoryQuery(memory_store)

    # Sprint E M2 — retrospective service
    if memory_store is not None:
        from theswarm.application.services.retrospective import RetrospectiveService
        app.state.retrospective_service = RetrospectiveService(memory_store)

    # Sprint E M4 — Improver agent reacts to StoryRejected
    if vcs_factory is not None:
        from theswarm.application.services.improver_agent import ImproverAgent
        from theswarm.domain.reporting.events import StoryRejected as _StoryRejected

        improver = ImproverAgent(
            vcs_factory=vcs_factory,
            project_repo=project_repo,
            report_repo=report_repo,
            memory_store=memory_store,
        )
        app.state.improver_agent = improver

        async def _on_story_rejected(evt: _StoryRejected) -> None:
            try:
                await improver.on_story_rejected(evt)
            except Exception:
                import logging as _logging
                _logging.getLogger(__name__).exception(
                    "Improver agent failed for report %s", evt.report_id,
                )

        event_bus.subscribe(_StoryRejected, _on_story_rejected)

    # Activity repository
    app.state.activity_repo = activity_repo

    # Report repository and artifact store
    app.state.report_repo = report_repo
    app.state.artifact_store = artifact_store

    # Persistence event handlers — store cycles and activities in SQLite
    cycle_persistence = CyclePersistenceHandler(cycle_repo)
    for evt_type in (CycleStarted, PhaseChanged, CycleCompleted, CycleFailed):
        event_bus.subscribe(evt_type, cycle_persistence.handle)
    if activity_repo is not None:
        activity_persistence = ActivityPersistenceHandler(activity_repo)
        event_bus.subscribe(AgentActivity, activity_persistence.handle)

    # Sprint D V2 — persist every cycle-scoped event for replay
    app.state.cycle_event_store = cycle_event_store
    if cycle_event_store is not None:
        cycle_event_persistence = CycleEventPersistenceHandler(cycle_event_store)
        for evt_type in (
            CycleStarted,
            PhaseChanged,
            AgentActivity,
            AgentThought,
            AgentStep,
            CycleCompleted,
            CycleFailed,
            BudgetExceeded,
        ):
            event_bus.subscribe(evt_type, cycle_event_persistence.handle)

    # Command handlers
    app.state.create_project_handler = CreateProjectHandler(project_repo)
    app.state.delete_project_handler = DeleteProjectHandler(project_repo)
    app.state.run_cycle_handler = RunCycleHandler(project_repo, cycle_repo, event_bus)
    app.state.update_project_config_handler = UpdateProjectConfigHandler(project_repo)

    # Sprint B: secret vault + audit DB
    app.state.secret_vault = secret_vault
    app.state.db = db

    # Sprint C F6 — VCS factory for story approve/reject/comment
    app.state.vcs_factory = vcs_factory

    # Sprint B C4 — CycleBlocked → SSE toast
    from theswarm.domain.cycles.events import CycleBlocked as _CycleBlocked

    async def _on_cycle_blocked(evt: _CycleBlocked) -> None:
        try:
            await hub.broadcast({
                "event_type": "cycle_blocked",
                "project_id": evt.project_id,
                "reason": evt.reason,
            })
        except Exception:
            pass

    event_bus.subscribe(_CycleBlocked, _on_cycle_blocked)

    # Schedule wiring (optional)
    app.state.schedule_repo = schedule_repo
    if schedule_repo is not None:
        app.state.get_schedule_query = GetScheduleQuery(schedule_repo)
        app.state.list_schedules_query = ListEnabledSchedulesQuery(schedule_repo)
        app.state.set_schedule_handler = SetScheduleHandler(project_repo, schedule_repo)
        app.state.disable_schedule_handler = DisableScheduleHandler(schedule_repo)
        app.state.delete_schedule_handler = DeleteScheduleHandler(schedule_repo)

    # Routes
    app.include_router(dashboard.router)
    app.include_router(projects.router)
    app.include_router(cycles.router)
    app.include_router(health.router)
    app.include_router(reports.router)
    app.include_router(webhooks.router)
    app.include_router(artifacts.router)
    app.include_router(demos.router)
    app.include_router(demos.public_router)
    app.include_router(metrics.router)
    app.include_router(features.router)
    app.include_router(fragments.router)
    app.include_router(api.router)

    # Static files
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app
