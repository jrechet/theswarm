"""FastAPI app factory for the web dashboard."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
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
from theswarm.application.events.bus import EventBus
from theswarm.application.queries.get_agent_thoughts import GetAgentThoughtsQuery
from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.get_project import GetProjectQuery
from theswarm.application.queries.get_schedule import (
    GetScheduleQuery,
    ListEnabledSchedulesQuery,
)
from theswarm.application.queries.list_cycles import ListCyclesQuery
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
    AgentStalled,
    AgentStep,
    AgentThought,
    BudgetExceeded,
    CycleCompleted,
    CycleFailed,
    CycleCancelled,
    CyclePaused,
    CycleStarted,
    PhaseChanged,
)
from theswarm.presentation.web.routes import api, artifacts, health, metrics, webhooks
from theswarm.presentation.web.auth import AuthWallMiddleware
from theswarm.presentation.web.shell import ShellMiddleware, current_shell
from theswarm.presentation.web.timing import TimingMiddleware
from theswarm.presentation.web.routes import agents_settings, auth_routes, customers, cycles_settings, github_setup, home, instance_settings, ops, player, project, requests_routes, spend, theater
from theswarm.presentation.web.sse import SSEHub

_HERE = Path(__file__).parent
_TEMPLATE_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"


_ASSET_VERSION = str(int(time.time()))


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
        context.setdefault("asset_v", _ASSET_VERSION)
        context.setdefault("shell", current_shell())  # the V3 rail, per request
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
    checkpoint_repo: object | None = None,
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

    # Phase 1.4 — sprint tracking
    if db is not None:
        # V3 M2 — customers, their members, the service the doors and the rail read
        from theswarm.application.services.customers import CustomerService
        from theswarm.infrastructure.persistence.customer_repo import (
            SQLiteCustomerRepository,
            SQLiteMemberRepository,
        )
        app.state.customer_repo = SQLiteCustomerRepository(db)
        app.state.member_repo = SQLiteMemberRepository(db)
        app.state.customer_service = CustomerService(
            app.state.customer_repo, app.state.member_repo, project_repo,
        )
        # V3 M5 — requests: a member's need, the owner's inbox; the tracker
        # follows the feature's cycle on the bus (building, then delivered)
        from theswarm.application.services.requests import RequestService, RequestTracker
        from theswarm.domain.reporting.events import DemoReady as _DemoReady
        from theswarm.infrastructure.persistence.customer_repo import SQLiteRequestRepository
        app.state.request_repo = SQLiteRequestRepository(db)
        app.state.request_service = RequestService(app.state.request_repo, project_repo)
        request_tracker = RequestTracker(app.state.request_service, project_repo)
        event_bus.subscribe(CycleStarted, request_tracker.on_cycle_started)
        event_bus.subscribe(_DemoReady, request_tracker.on_demo_ready)
        # Settings → Agents: each persona's Claude model and effort, the owner's choice
        from theswarm.application.services.agent_settings import AgentSettingsService
        from theswarm.infrastructure.persistence.agent_settings_repo import SQLiteAgentSettingsRepository

        app.state.agent_settings = AgentSettingsService(SQLiteAgentSettingsRepository(db))
        # Settings → Cycles: how many run at once, in all and per project
        from theswarm.application.services.cycle_limits import CycleLimitsService
        from theswarm.infrastructure.persistence.cycle_limits_repo import SQLiteCycleLimits

        app.state.cycle_limits = CycleLimitsService(SQLiteCycleLimits(db))
        # A3.1: what the owner says to a running cycle, read by its working agent
        from theswarm.application.services.cycle_inbox import CycleInbox
        from theswarm.infrastructure.persistence.cycle_inbox_repo import SQLiteCycleInbox

        app.state.cycle_inbox = CycleInbox(SQLiteCycleInbox(db), event_bus)

        # The PO tells the customer what was built, when a demo lands (V3, folded into the PO)
        import os as _os

        from theswarm.application.services.demo_summary import DemoSummaryWriter
        from theswarm.infrastructure.persistence.summary_repo import SQLiteDemoSummaryRepository
        from theswarm.presentation.web.routes.player import verdict_of as _verdict_of

        app.state.demo_summary_repo = SQLiteDemoSummaryRepository(db)

        async def _summary_repo_name(project_id: str) -> str:
            if "/" in project_id:
                return project_id
            project = await project_repo.get(project_id)
            return str(project.repo) if project is not None else project_id

        async def _what_was_asked(repo: str, number: int | None) -> str:
            from theswarm.application.services.pinned_issue import load_pinned_issue
            from theswarm.presentation.web.routes.project import shown_body

            pinned = await load_pinned_issue(repo, number)
            issue = pinned.issue or {}
            return f"{issue.get('title', '')}\n{shown_body(issue.get('body'))}".strip()

        def _summary_claude():
            # the PO's Claude (Settings → Agents), else SWARM_SUMMARY_MODEL, else the instance's model
            return app.state.agent_settings.claude_for("po", base_model=_os.environ.get("SWARM_SUMMARY_MODEL") or None)

        app.state.demo_summary_writer = DemoSummaryWriter(
            report_repo, app.state.demo_summary_repo, _summary_claude, verdict_of=_verdict_of,
            asked_for=_what_was_asked, repo_of=_summary_repo_name,
        ) if report_repo is not None else None
        if app.state.demo_summary_writer is not None and _os.environ.get("SWARM_DEMO_SUMMARY", "1") != "0":
            event_bus.subscribe(_DemoReady, app.state.demo_summary_writer.on_demo_ready)
        # The owner's spend view: alerts posted on the PO's channel when a cycle finishes
        # (the card and /api/spend read the same rows; the server hands the chat over)
        from theswarm.application.services.spend import SpendWatch, lookups as _spend_lookups

        async def _spend_lookup():
            return await _spend_lookups(project_repo, app.state.customer_repo)

        from theswarm.infrastructure.persistence.spend_alert_ledger import SQLiteSpendAlertLedger

        app.state.spend_watch = SpendWatch(cycle_repo, _spend_lookup, ledger=SQLiteSpendAlertLedger(db))
        event_bus.subscribe(CycleCompleted, app.state.spend_watch.on_cycle_finished)
        event_bus.subscribe(CycleFailed, app.state.spend_watch.on_cycle_finished)

    # Queries
    app.state.list_projects_query = ListProjectsQuery(project_repo)
    app.state.get_project_query = GetProjectQuery(project_repo)
    app.state.get_cycle_status_query = GetCycleStatusQuery(cycle_repo)
    app.state.list_cycles_query = ListCyclesQuery(cycle_repo)
    app.state.get_dashboard_query = GetDashboardQuery(project_repo, cycle_repo, activity_repo)
    app.state.get_agent_thoughts_query = GetAgentThoughtsQuery(cycle_event_store)


    # Sprint E M1 — memory viewer
    app.state.memory_store = memory_store


    # Activity repository
    app.state.activity_repo = activity_repo

    # Report repository and artifact store
    app.state.report_repo = report_repo
    app.state.artifact_store = artifact_store

    # Sprint G1 — checkpoint repository for cycle resume
    app.state.checkpoint_repo = checkpoint_repo

    # Persistence event handlers — store cycles and activities in SQLite
    cycle_persistence = CyclePersistenceHandler(cycle_repo)
    for evt_type in (CycleStarted, PhaseChanged, CycleCompleted, CycleFailed, CycleCancelled, CyclePaused):
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
            AgentStalled,
            AgentThought,
            AgentStep,
            CycleCompleted,
            CycleFailed,
            CycleCancelled,
            BudgetExceeded,
        ):
            event_bus.subscribe(evt_type, cycle_event_persistence.handle)

    # Role assignment service (codenames + core roster on project create)
    role_assignment_repo = None
    role_assignment_service = None
    if db is not None:
        try:
            from theswarm.application.services.role_assignment_service import (
                RoleAssignmentService,
            )
            from theswarm.infrastructure.agents.role_assignment_repo import (
                SQLiteRoleAssignmentRepository,
            )

            role_assignment_repo = SQLiteRoleAssignmentRepository(db)
            role_assignment_service = RoleAssignmentService(
                role_assignment_repo, event_bus=event_bus,
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire RoleAssignmentService",
            )
    app.state.role_assignment_service = role_assignment_service


    # Phase C — PO intelligence (proposals, OKRs, policy, digest, signals)
    proposal_repo = None
    policy_repo = None
    signal_repo = None
    proposal_service = None
    if db is not None:
        try:
            from theswarm.application.services.policy_filter import PolicyFilter
            from theswarm.application.services.proposal_service import (
                ProposalService,
            )
            from theswarm.infrastructure.product import (
                SQLiteDigestRepository,
                SQLiteOKRRepository,
                SQLitePolicyRepository,
                SQLiteProposalRepository,
                SQLiteSignalRepository,
            )

            proposal_repo = SQLiteProposalRepository(db)
            policy_repo = SQLitePolicyRepository(db)
            signal_repo = SQLiteSignalRepository(db)

            policy_filter = PolicyFilter(policy_repo)
            proposal_service = ProposalService(
                proposal_repo, policy_filter, signal_repo=signal_repo,
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire PO intelligence (Phase C)",
            )
    app.state.proposal_service = proposal_service
















    # Command handlers
    app.state.create_project_handler = CreateProjectHandler(
        project_repo, role_service=role_assignment_service,
    )
    app.state.delete_project_handler = DeleteProjectHandler(project_repo)
    app.state.run_cycle_handler = RunCycleHandler(project_repo, cycle_repo, event_bus)

    # Sprint B: secret vault + audit DB
    app.state.secret_vault = secret_vault
    # V2 M6: the scored harness runs, read by the repo page and written by
    # POST /api/evals/runs; None without a database (stub/tests without one).
    if db is not None:
        from theswarm.infrastructure.persistence.sqlite_repos import SQLiteEvalRunRepository

        app.state.eval_run_repo = SQLiteEvalRunRepository(db)
    else:
        app.state.eval_run_repo = None

    # DevOps D1 — the stack declared in theswarm.yaml, read on a cadence; the
    # server starts the loop, the home and /api/devops read the last report.
    # SWARM_STACK_FILE names another file (the suite points it at none).
    import os as _os

    from theswarm.agents.devops import gather as devops_gather, load_stack
    from theswarm.application.services.ops_watch import OpsWatch

    stack = load_stack(_os.environ.get("SWARM_STACK_FILE", "theswarm.yaml"))
    if stack:
        async def _harness_runs(repo: str) -> list[dict]:
            store = getattr(app.state, "eval_run_repo", None)
            return await store.list_for_repo(repo, limit=10) if store is not None else []

        # D3 — proposals: raised from each report, decided by the owner on the home.
        from theswarm.agents.devops import run_host
        from theswarm.application.services.proposals import ProposalService
        from theswarm.infrastructure.persistence.ops_repo import SQLiteProposalRepository

        app.state.proposal_service = ProposalService(SQLiteProposalRepository(db), stack, run_host) if db is not None else None

        async def _raise_proposals(report):
            if app.state.proposal_service is not None:
                await app.state.proposal_service.raise_from(report.findings, report.facts)
            # the fifth station: a report closes the deploy watches it can answer
            from theswarm.application.services.devops_cycles import resolve_deploys

            await resolve_deploys(report, cycle_repo, app.state.cycle_event_store, event_bus.publish)

        app.state.ops_watch = OpsWatch(
            lambda: devops_gather(stack, harness=_harness_runs),
            interval_s=int(_os.environ.get("SWARM_DEVOPS_INTERVAL_SECONDS", "600") or 600),
            on_report=_raise_proposals,
            preflight_gather=lambda: devops_gather(stack, light=True),
        )
        # D4 — improvements as PRs: the owner's click measures, asks Claude, opens the PR.
        from theswarm.agents.devops import self_repo
        from theswarm.agents.devops_improve import propose_improvement

        if self_repo(stack):
            async def _improver(report):
                from theswarm.tools.claude import ClaudeCLI
                from theswarm.tools.github import GitHubClient

                settings = getattr(app.state, "agent_settings", None)
                claude = settings.claude_for("devops") if settings is not None else ClaudeCLI(model=_os.environ.get("SWARM_CLAUDE_MODEL", "sonnet"))
                return await propose_improvement(stack, report, claude,
                                                 GitHubClient(self_repo(stack)))

            app.state.ops_watch.configure_improver(_improver)
    else:
        app.state.ops_watch = None
        app.state.proposal_service = None

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

    if schedule_repo is not None:
        app.state.get_schedule_query = GetScheduleQuery(schedule_repo)
        app.state.list_schedules_query = ListEnabledSchedulesQuery(schedule_repo)
        app.state.set_schedule_handler = SetScheduleHandler(project_repo, schedule_repo)
        app.state.delete_schedule_handler = DeleteScheduleHandler(schedule_repo)

    # Routes
    app.include_router(theater.router)  # V3 M4: /cycles/{id}, the theater
    app.include_router(project.router)  # V3 M3: /c/{slug}/p/{name}, its features, /r/{owner}/{name} → there
    app.include_router(customers.router)  # V3 M2: /settings/customers, /invite/{token}, /c/{slug}
    app.include_router(requests_routes.router)  # V3 M5: /requests — the inbox, a member's list and composer
    app.include_router(ops.router)  # DevOps D1: /api/devops, /ops/refresh
    app.include_router(spend.router)  # the owner's spend view: /api/spend
    app.include_router(instance_settings.router)  # V3 M6: /settings/instance — the vault-backed keys and URLs
    app.include_router(agents_settings.router)  # /settings/agents — each persona's Claude model and effort
    app.include_router(cycles_settings.router)  # /settings/cycles — how many cycles at once, in all and per project
    app.include_router(home.router)  # owns `/`: the owner's home, a member's customer
    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(artifacts.router)
    app.include_router(player.router)  # V3 M4: /demos/{id}, /demos/{id}/play → there
    app.include_router(player.public_router)  # /d/{short}, outside the wall
    app.include_router(metrics.router)  # Prometheus text, behind the wall — a machine endpoint, not a page
    app.include_router(api.router)
    app.include_router(auth_routes.router)
    app.include_router(github_setup.router)

    # A 404 is a page for a browser (the shell when signed in), the usual JSON for a client (M7).
    @app.exception_handler(StarletteHTTPException)  # the router's own 404 is Starlette's, FastAPI's subclasses it
    async def _http_exception(request, exc: StarletteHTTPException):
        if exc.status_code == 404 and "text/html" in request.headers.get("accept", ""):
            message = exc.detail if isinstance(exc.detail, str) and exc.detail != "Not Found" else ""
            return app.state.templates.TemplateResponse("not_found.html", {
                "request": request, "message": message, "path": request.url.path,
            }, status_code=404)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    # Static files
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # The V3 shell (rail, Claude's health, who is signed in) for every HTML page.
    app.add_middleware(ShellMiddleware, base_path=base_path.rstrip("/"))
    # Issue #38 — the wall goes up last so it fronts every route above.
    app.add_middleware(AuthWallMiddleware, base_path=base_path.rstrip("/"))
    # Issue #316 — outermost: the clock ahead of the wall and the rail, timing the whole request.
    app.add_middleware(TimingMiddleware)

    return app
