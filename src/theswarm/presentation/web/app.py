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
from theswarm.presentation.web.routes import analyst, api, architect, artifacts, autonomy_config, chat, chief_of_staff, cycles, dashboard, demos, designer, dev_rigour, features, fragments, health, hitl, metrics, product, projects, prompt_library, qa, refactor_programs, release, reports, scout, security, semantic_memory, sre, team, techlead, webhooks, writer
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

    # Sprint G1 — checkpoint repository for cycle resume
    app.state.checkpoint_repo = checkpoint_repo

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
    app.state.role_assignment_repo = role_assignment_repo
    app.state.role_assignment_service = role_assignment_service
    if role_assignment_repo is not None:
        from theswarm.application.queries.list_role_assignments import (
            ListRoleAssignmentsQuery,
        )
        app.state.list_role_assignments_query = ListRoleAssignmentsQuery(
            role_assignment_repo,
        )

    # Phase B — Dashboard chat + HITL audit
    chat_repo = None
    chat_service = None
    hitl_audit_repo = None
    if db is not None and role_assignment_service is not None:
        try:
            from theswarm.application.services.chat_service import ChatService
            from theswarm.infrastructure.chat.chat_repo import (
                SQLiteChatRepository,
                SQLiteHITLAuditRepository,
            )

            chat_repo = SQLiteChatRepository(db)
            hitl_audit_repo = SQLiteHITLAuditRepository(db)
            chat_service = ChatService(
                chat_repo=chat_repo,
                role_service=role_assignment_service,
                event_bus=event_bus,
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception("Failed to wire ChatService")
    app.state.chat_repo = chat_repo
    app.state.chat_service = chat_service
    app.state.hitl_audit_repo = hitl_audit_repo

    # Phase C — PO intelligence (proposals, OKRs, policy, digest, signals)
    proposal_repo = None
    okr_repo = None
    policy_repo = None
    signal_repo = None
    digest_repo = None
    proposal_service = None
    insight_digest_service = None
    watch_runner = None
    if db is not None:
        try:
            from theswarm.application.services.insight_digest import (
                InsightDigestService,
            )
            from theswarm.application.services.policy_filter import PolicyFilter
            from theswarm.application.services.proposal_service import (
                ProposalService,
            )
            from theswarm.application.services.watch_jobs import WatchRunner
            from theswarm.infrastructure.product import (
                SQLiteDigestRepository,
                SQLiteOKRRepository,
                SQLitePolicyRepository,
                SQLiteProposalRepository,
                SQLiteSignalRepository,
            )

            proposal_repo = SQLiteProposalRepository(db)
            okr_repo = SQLiteOKRRepository(db)
            policy_repo = SQLitePolicyRepository(db)
            signal_repo = SQLiteSignalRepository(db)
            digest_repo = SQLiteDigestRepository(db)

            policy_filter = PolicyFilter(policy_repo)
            proposal_service = ProposalService(
                proposal_repo, policy_filter, signal_repo=signal_repo,
            )
            insight_digest_service = InsightDigestService(
                signal_repo, proposal_repo, digest_repo,
            )
            watch_runner = WatchRunner(
                project_repo=project_repo,
                proposal_service=proposal_service,
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire PO intelligence (Phase C)",
            )
    app.state.proposal_repo = proposal_repo
    app.state.okr_repo = okr_repo
    app.state.policy_repo = policy_repo
    app.state.signal_repo = signal_repo
    app.state.digest_repo = digest_repo
    app.state.proposal_service = proposal_service
    app.state.insight_digest_service = insight_digest_service
    app.state.watch_runner = watch_runner

    # Phase D — TechLead intelligence (ADRs, debt, deps, reviews, second-opinion)
    adr_repo = None
    debt_repo = None
    dep_finding_repo = None
    verdict_repo = None
    critical_path_repo = None
    adr_service = None
    debt_service = None
    dependency_radar = None
    review_calibration_service = None
    second_opinion_service = None
    if db is not None:
        try:
            from theswarm.application.services.adr_service import ADRService
            from theswarm.application.services.debt_service import DebtService
            from theswarm.application.services.dependency_radar import (
                DependencyRadar,
            )
            from theswarm.application.services.review_calibration import (
                ReviewCalibrationService,
            )
            from theswarm.application.services.second_opinion import (
                SecondOpinionService,
            )
            from theswarm.infrastructure.techlead import (
                SQLiteADRRepository,
                SQLiteCriticalPathRepository,
                SQLiteDebtRepository,
                SQLiteDepFindingRepository,
                SQLiteReviewVerdictRepository,
            )

            adr_repo = SQLiteADRRepository(db)
            debt_repo = SQLiteDebtRepository(db)
            dep_finding_repo = SQLiteDepFindingRepository(db)
            verdict_repo = SQLiteReviewVerdictRepository(db)
            critical_path_repo = SQLiteCriticalPathRepository(db)

            adr_service = ADRService(adr_repo)
            debt_service = DebtService(debt_repo)
            dependency_radar = DependencyRadar(project_repo, dep_finding_repo)
            review_calibration_service = ReviewCalibrationService(verdict_repo)
            second_opinion_service = SecondOpinionService(critical_path_repo)
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire TechLead intelligence (Phase D)",
            )
    app.state.adr_repo = adr_repo
    app.state.debt_repo = debt_repo
    app.state.dep_finding_repo = dep_finding_repo
    app.state.review_verdict_repo = verdict_repo
    app.state.critical_path_repo = critical_path_repo
    app.state.adr_service = adr_service
    app.state.debt_service = debt_service
    app.state.dependency_radar = dependency_radar
    app.state.review_calibration_service = review_calibration_service
    app.state.second_opinion_service = second_opinion_service

    # Phase E — Dev rigour services (depend on db init)
    dev_thought_service = None
    tdd_gate_service = None
    refactor_preflight_service = None
    self_review_service = None
    coverage_delta_service = None
    if db is not None:
        try:
            from theswarm.application.services.dev_rigour import (
                CoverageDeltaService,
                DevThoughtService,
                RefactorPreflightService,
                SelfReviewService,
                TddGateService,
            )
            from theswarm.infrastructure.dev_rigour import (
                SQLiteCoverageDeltaRepository,
                SQLiteDevThoughtRepository,
                SQLiteRefactorPreflightRepository,
                SQLiteSelfReviewRepository,
                SQLiteTddArtifactRepository,
            )

            dev_thought_service = DevThoughtService(
                SQLiteDevThoughtRepository(db),
            )
            tdd_gate_service = TddGateService(SQLiteTddArtifactRepository(db))
            refactor_preflight_service = RefactorPreflightService(
                SQLiteRefactorPreflightRepository(db),
            )
            self_review_service = SelfReviewService(
                SQLiteSelfReviewRepository(db),
            )
            coverage_delta_service = CoverageDeltaService(
                SQLiteCoverageDeltaRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Dev rigour (Phase E)",
            )
    app.state.dev_thought_service = dev_thought_service
    app.state.tdd_gate_service = tdd_gate_service
    app.state.refactor_preflight_service = refactor_preflight_service
    app.state.self_review_service = self_review_service
    app.state.coverage_delta_service = coverage_delta_service

    # Phase F — QA enrichments services (depend on db init)
    archetype_mix_service = None
    flake_tracker_service = None
    quarantine_service = None
    quality_gate_service = None
    outcome_card_service = None
    if db is not None:
        try:
            from theswarm.application.services.qa import (
                ArchetypeMixService,
                FlakeTrackerService,
                OutcomeCardService,
                QualityGateService,
                QuarantineService,
            )
            from theswarm.infrastructure.qa import (
                SQLiteFlakeRecordRepository,
                SQLiteOutcomeCardRepository,
                SQLiteQualityGateRepository,
                SQLiteQuarantineRepository,
                SQLiteTestPlanRepository,
            )

            archetype_mix_service = ArchetypeMixService(
                SQLiteTestPlanRepository(db),
            )
            flake_tracker_service = FlakeTrackerService(
                SQLiteFlakeRecordRepository(db),
            )
            quarantine_service = QuarantineService(
                SQLiteQuarantineRepository(db),
            )
            quality_gate_service = QualityGateService(
                SQLiteQualityGateRepository(db),
            )
            outcome_card_service = OutcomeCardService(
                SQLiteOutcomeCardRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire QA enrichments (Phase F)",
            )
    app.state.archetype_mix_service = archetype_mix_service
    app.state.flake_tracker_service = flake_tracker_service
    app.state.quarantine_service = quarantine_service
    app.state.quality_gate_service = quality_gate_service
    app.state.outcome_card_service = outcome_card_service

    # Phase G — Scout services (depend on db init)
    intel_source_service = None
    intel_feed_service = None
    intel_cluster_service = None
    if db is not None:
        try:
            from theswarm.application.services.scout import (
                IntelClusterService,
                IntelFeedService,
                IntelSourceService,
            )
            from theswarm.infrastructure.scout import (
                SQLiteIntelClusterRepository,
                SQLiteIntelItemRepository,
                SQLiteIntelSourceRepository,
            )

            _scout_item_repo = SQLiteIntelItemRepository(db)
            _scout_cluster_repo = SQLiteIntelClusterRepository(db)
            intel_source_service = IntelSourceService(
                SQLiteIntelSourceRepository(db),
            )
            intel_feed_service = IntelFeedService(_scout_item_repo)
            intel_cluster_service = IntelClusterService(
                _scout_cluster_repo, _scout_item_repo,
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Scout (Phase G)",
            )
    app.state.intel_source_service = intel_source_service
    app.state.intel_feed_service = intel_feed_service
    app.state.intel_cluster_service = intel_cluster_service

    # Phase H — Designer services (depend on db init)
    design_system_service = None
    component_inventory_service = None
    design_brief_service = None
    visual_regression_service = None
    anti_template_service = None
    if db is not None:
        try:
            from theswarm.application.services.designer import (
                AntiTemplateService,
                ComponentInventoryService,
                DesignBriefService,
                DesignSystemService,
                VisualRegressionService,
            )
            from theswarm.infrastructure.designer import (
                SQLiteAntiTemplateRepository,
                SQLiteComponentRepository,
                SQLiteDesignBriefRepository,
                SQLiteDesignTokenRepository,
                SQLiteVisualRegressionRepository,
            )

            design_system_service = DesignSystemService(
                SQLiteDesignTokenRepository(db),
            )
            component_inventory_service = ComponentInventoryService(
                SQLiteComponentRepository(db),
            )
            design_brief_service = DesignBriefService(
                SQLiteDesignBriefRepository(db),
            )
            visual_regression_service = VisualRegressionService(
                SQLiteVisualRegressionRepository(db),
            )
            anti_template_service = AntiTemplateService(
                SQLiteAntiTemplateRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Designer (Phase H)",
            )
    app.state.design_system_service = design_system_service
    app.state.component_inventory_service = component_inventory_service
    app.state.design_brief_service = design_brief_service
    app.state.visual_regression_service = visual_regression_service
    app.state.anti_template_service = anti_template_service

    # Phase I — Security + SRE services (depend on db init)
    threat_model_service = None
    data_inventory_service = None
    security_finding_service = None
    sbom_service = None
    authz_service = None
    deployment_service = None
    incident_service = None
    cost_service = None
    if db is not None:
        try:
            from theswarm.application.services.security import (
                AuthZService,
                DataInventoryService,
                SBOMService,
                SecurityFindingService,
                ThreatModelService,
            )
            from theswarm.application.services.sre import (
                CostService,
                DeploymentService,
                IncidentService,
            )
            from theswarm.infrastructure.security import (
                SQLiteAuthZRepository,
                SQLiteDataInventoryRepository,
                SQLiteFindingRepository,
                SQLiteSBOMRepository,
                SQLiteThreatModelRepository,
            )
            from theswarm.infrastructure.sre import (
                SQLiteCostRepository,
                SQLiteDeploymentRepository,
                SQLiteIncidentRepository,
            )

            threat_model_service = ThreatModelService(
                SQLiteThreatModelRepository(db),
            )
            data_inventory_service = DataInventoryService(
                SQLiteDataInventoryRepository(db),
            )
            security_finding_service = SecurityFindingService(
                SQLiteFindingRepository(db),
            )
            sbom_service = SBOMService(SQLiteSBOMRepository(db))
            authz_service = AuthZService(SQLiteAuthZRepository(db))
            deployment_service = DeploymentService(
                SQLiteDeploymentRepository(db),
            )
            incident_service = IncidentService(SQLiteIncidentRepository(db))
            cost_service = CostService(SQLiteCostRepository(db))
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Security + SRE (Phase I)",
            )
    app.state.threat_model_service = threat_model_service
    app.state.data_inventory_service = data_inventory_service
    app.state.security_finding_service = security_finding_service
    app.state.sbom_service = sbom_service
    app.state.authz_service = authz_service
    app.state.deployment_service = deployment_service
    app.state.incident_service = incident_service
    app.state.cost_service = cost_service

    # Phase J — Analyst services (depend on db init)
    metric_definition_service = None
    instrumentation_plan_service = None
    outcome_observation_service = None
    if db is not None:
        try:
            from theswarm.application.services.analyst import (
                InstrumentationPlanService,
                MetricDefinitionService,
                OutcomeObservationService,
            )
            from theswarm.infrastructure.analyst import (
                SQLiteInstrumentationPlanRepository,
                SQLiteMetricDefinitionRepository,
                SQLiteOutcomeObservationRepository,
            )

            metric_definition_service = MetricDefinitionService(
                SQLiteMetricDefinitionRepository(db),
            )
            instrumentation_plan_service = InstrumentationPlanService(
                SQLiteInstrumentationPlanRepository(db),
            )
            outcome_observation_service = OutcomeObservationService(
                SQLiteOutcomeObservationRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Analyst (Phase J)",
            )
    app.state.metric_definition_service = metric_definition_service
    app.state.instrumentation_plan_service = instrumentation_plan_service
    app.state.outcome_observation_service = outcome_observation_service

    # Phase J — Writer services (depend on db init)
    doc_artifact_service = None
    quickstart_check_service = None
    changelog_service = None
    if db is not None:
        try:
            from theswarm.application.services.writer import (
                ChangelogService,
                DocArtifactService,
                QuickstartCheckService,
            )
            from theswarm.infrastructure.writer.changelog_repo import (
                SQLiteChangelogEntryRepository,
            )
            from theswarm.infrastructure.writer.doc_repo import (
                SQLiteDocArtifactRepository,
            )
            from theswarm.infrastructure.writer.quickstart_repo import (
                SQLiteQuickstartCheckRepository,
            )

            doc_artifact_service = DocArtifactService(
                SQLiteDocArtifactRepository(db),
            )
            quickstart_check_service = QuickstartCheckService(
                SQLiteQuickstartCheckRepository(db),
            )
            changelog_service = ChangelogService(
                SQLiteChangelogEntryRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Writer (Phase J)",
            )
    app.state.doc_artifact_service = doc_artifact_service
    app.state.quickstart_check_service = quickstart_check_service
    app.state.changelog_service = changelog_service

    # Phase J — Release services (depend on db init)
    release_version_service = None
    feature_flag_service = None
    rollback_action_service = None
    if db is not None:
        try:
            from theswarm.application.services.release import (
                FeatureFlagService,
                ReleaseVersionService,
                RollbackActionService,
            )
            from theswarm.infrastructure.release.flag_repo import (
                SQLiteFeatureFlagRepository,
            )
            from theswarm.infrastructure.release.rollback_repo import (
                SQLiteRollbackActionRepository,
            )
            from theswarm.infrastructure.release.version_repo import (
                SQLiteReleaseVersionRepository,
            )

            release_version_service = ReleaseVersionService(
                SQLiteReleaseVersionRepository(db),
            )
            feature_flag_service = FeatureFlagService(
                SQLiteFeatureFlagRepository(db),
            )
            rollback_action_service = RollbackActionService(
                SQLiteRollbackActionRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Release (Phase J)",
            )
    app.state.release_version_service = release_version_service
    app.state.feature_flag_service = feature_flag_service
    app.state.rollback_action_service = rollback_action_service

    # Phase K — Architect services (depend on db init)
    paved_road_service = None
    portfolio_adr_service = None
    direction_brief_service = None
    if db is not None:
        try:
            from theswarm.application.services.architect import (
                DirectionBriefService,
                PavedRoadService,
                PortfolioADRService,
            )
            from theswarm.infrastructure.architect.adr_repo import (
                SQLitePortfolioADRRepository,
            )
            from theswarm.infrastructure.architect.brief_repo import (
                SQLiteDirectionBriefRepository,
            )
            from theswarm.infrastructure.architect.rule_repo import (
                SQLitePavedRoadRuleRepository,
            )

            paved_road_service = PavedRoadService(
                SQLitePavedRoadRuleRepository(db),
            )
            portfolio_adr_service = PortfolioADRService(
                SQLitePortfolioADRRepository(db),
            )
            direction_brief_service = DirectionBriefService(
                SQLiteDirectionBriefRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Architect (Phase K)",
            )
    app.state.paved_road_service = paved_road_service
    app.state.portfolio_adr_service = portfolio_adr_service
    app.state.direction_brief_service = direction_brief_service

    # Phase K — Chief of Staff services (depend on db init)
    routing_service = None
    budget_policy_service = None
    onboarding_service = None
    archive_service = None
    if db is not None:
        try:
            from theswarm.application.services.chief_of_staff import (
                ArchiveService,
                BudgetPolicyService,
                OnboardingService,
                RoutingService,
            )
            from theswarm.infrastructure.chief_of_staff.archive_repo import (
                SQLiteArchivedProjectRepository,
            )
            from theswarm.infrastructure.chief_of_staff.budget_repo import (
                SQLiteBudgetPolicyRepository,
            )
            from theswarm.infrastructure.chief_of_staff.onboarding_repo import (
                SQLiteOnboardingStepRepository,
            )
            from theswarm.infrastructure.chief_of_staff.routing_repo import (
                SQLiteRoutingRuleRepository,
            )

            routing_service = RoutingService(SQLiteRoutingRuleRepository(db))
            budget_policy_service = BudgetPolicyService(
                SQLiteBudgetPolicyRepository(db),
            )
            onboarding_service = OnboardingService(
                SQLiteOnboardingStepRepository(db),
            )
            archive_service = ArchiveService(
                SQLiteArchivedProjectRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire Chief of Staff (Phase K)",
            )
    app.state.routing_service = routing_service
    app.state.budget_policy_service = budget_policy_service
    app.state.onboarding_service = onboarding_service
    app.state.archive_service = archive_service

    # Phase L — refactor programs
    refactor_program_service = None
    if db is not None:
        try:
            from theswarm.application.services.refactor_programs import (
                RefactorProgramService,
            )
            from theswarm.infrastructure.refactor_programs.program_repo import (
                SQLiteRefactorProgramRepository,
            )

            refactor_program_service = RefactorProgramService(
                SQLiteRefactorProgramRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire refactor programs (Phase L)",
            )
    app.state.refactor_program_service = refactor_program_service

    # Phase L — semantic memory
    semantic_memory_service = None
    if db is not None:
        try:
            from theswarm.application.services.semantic_memory import (
                SemanticMemoryService,
            )
            from theswarm.infrastructure.semantic_memory.entry_repo import (
                SQLiteSemanticMemoryRepository,
            )

            semantic_memory_service = SemanticMemoryService(
                SQLiteSemanticMemoryRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire semantic memory (Phase L)",
            )
    app.state.semantic_memory_service = semantic_memory_service

    # Phase L — prompt library
    prompt_library_service = None
    if db is not None:
        try:
            from theswarm.application.services.prompt_library import (
                PromptLibraryService,
            )
            from theswarm.infrastructure.prompt_library.template_repo import (
                SQLitePromptAuditRepository,
                SQLitePromptTemplateRepository,
            )

            prompt_library_service = PromptLibraryService(
                SQLitePromptTemplateRepository(db),
                SQLitePromptAuditRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire prompt library (Phase L)",
            )
    app.state.prompt_library_service = prompt_library_service

    # Phase L — autonomy-spectrum config
    autonomy_config_service = None
    if db is not None:
        try:
            from theswarm.application.services.autonomy_config import (
                AutonomyConfigService,
            )
            from theswarm.infrastructure.autonomy_config.config_repo import (
                SQLiteAutonomyConfigRepository,
            )

            autonomy_config_service = AutonomyConfigService(
                SQLiteAutonomyConfigRepository(db),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "Failed to wire autonomy config (Phase L)",
            )
    app.state.autonomy_config_service = autonomy_config_service

    # Command handlers
    app.state.create_project_handler = CreateProjectHandler(
        project_repo, role_service=role_assignment_service,
    )
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
    app.include_router(team.router)
    app.include_router(chat.router)
    app.include_router(hitl.router)
    app.include_router(product.router)
    app.include_router(techlead.router)
    app.include_router(dev_rigour.router)
    app.include_router(qa.router)
    app.include_router(scout.router)
    app.include_router(designer.router)
    app.include_router(security.router)
    app.include_router(sre.router)
    app.include_router(analyst.router)
    app.include_router(writer.router)
    app.include_router(release.router)
    app.include_router(architect.router)
    app.include_router(chief_of_staff.router)
    app.include_router(refactor_programs.router)
    app.include_router(semantic_memory.router)
    app.include_router(prompt_library.router)
    app.include_router(autonomy_config.router)
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
