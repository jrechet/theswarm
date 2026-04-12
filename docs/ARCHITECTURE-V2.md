# TheSwarm v2.0 — DDD Architecture Plan

**Date:** 2026-04-12
**Status:** APPROVED FOR IMPLEMENTATION
**Scope:** Full rewrite of package structure using Domain-Driven Design + Clean Architecture

---

## Bounded Contexts

```
┌──────────────────────────────────────────────────────────────────┐
│                        TheSwarm v2.0                             │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │   Projects    │  │    Cycles    │  │       Agents         │   │
│  │              │  │              │  │  PO, TL, Dev, QA,    │   │
│  │  Registry    │  │  Orchestrate │  │  Improver            │   │
│  │  Config      │  │  Phases      │  │  State graphs        │   │
│  │  Framework   │  │  Budget      │  │  Context loading     │   │
│  │  Detection   │  │  Checkpoint  │  │                      │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
│         │                 │                      │               │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌──────────┴───────────┐   │
│  │   Tickets    │  │   Memory     │  │     Reporting        │   │
│  │              │  │              │  │                      │   │
│  │  GitHub      │  │  Learnings   │  │  Demo reports        │   │
│  │  Jira        │  │  Retrospect  │  │  Screenshots         │   │
│  │  Linear      │  │  Cross-proj  │  │  Video recordings    │   │
│  │  GitLab      │  │  Compaction  │  │  Metrics & trends    │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │     Chat     │  │     VCS      │  │     Scheduling       │   │
│  │              │  │              │  │                      │   │
│  │  Mattermost  │  │  GitHub      │  │  Cron triggers       │   │
│  │  Slack (fut) │  │  GitLab(fut) │  │  Webhook triggers    │   │
│  │  NLU/Persona │  │  Git CLI     │  │  Queue management    │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Clean Architecture Layers

```
┌─────────────────────────────────────────────┐
│              Presentation                    │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │     TUI     │  │      Web App         │  │
│  │  (Textual)  │  │  (FastAPI + HTMX)    │  │
│  └──────┬──────┘  └──────────┬───────────┘  │
│         └──────────┬─────────┘              │
│                    │                         │
│ ┌──────────────────▼────────────────────┐   │
│ │          Application Layer            │   │
│ │  Use Cases / Commands / Queries       │   │
│ │  DTOs / Event Bus / CQRS             │   │
│ └──────────────────┬────────────────────┘   │
│                    │                         │
│ ┌──────────────────▼────────────────────┐   │
│ │           Domain Layer                │   │
│ │  Entities / Value Objects / Ports     │   │
│ │  Domain Services / Domain Events      │   │
│ └──────────────────┬────────────────────┘   │
│                    │                         │
│ ┌──────────────────▼────────────────────┐   │
│ │        Infrastructure Layer           │   │
│ │  GitHub / Mattermost / Claude / Git   │   │
│ │  SQLite / Playwright / Semgrep        │   │
│ └───────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## New Package Structure

```
src/theswarm/
│
├── domain/                          # Pure domain logic — no external deps
│   ├── __init__.py
│   │
│   ├── projects/                    # Bounded Context: Project Management
│   │   ├── __init__.py
│   │   ├── entities.py              # Project, ProjectConfig
│   │   ├── value_objects.py         # RepoUrl, Framework, DefaultBranch
│   │   ├── ports.py                 # ProjectRepository (protocol)
│   │   └── services.py             # FrameworkDetector, ProjectValidator
│   │
│   ├── cycles/                      # Bounded Context: Cycle Orchestration
│   │   ├── __init__.py
│   │   ├── entities.py              # Cycle, CyclePhase, CycleResult
│   │   ├── value_objects.py         # Budget, TokenUsage, CycleId
│   │   ├── ports.py                 # CycleRepository, CycleEventEmitter
│   │   ├── services.py             # CycleOrchestrator, BudgetEnforcer
│   │   └── events.py               # CycleStarted, PhaseChanged, CycleCompleted
│   │
│   ├── agents/                      # Bounded Context: Agent Domain
│   │   ├── __init__.py
│   │   ├── entities.py              # Agent, AgentRole, AgentState
│   │   ├── value_objects.py         # Phase, TaskResult, ReviewDecision
│   │   ├── ports.py                 # LLMPort, VCSPort, TicketPort
│   │   ├── po.py                    # PO agent domain logic
│   │   ├── techlead.py              # TechLead agent domain logic
│   │   ├── dev.py                   # Dev agent domain logic
│   │   ├── qa.py                    # QA agent domain logic
│   │   └── improver.py             # NEW: Self-improvement agent
│   │
│   ├── tickets/                     # Bounded Context: Ticket Management
│   │   ├── __init__.py
│   │   ├── entities.py              # Ticket, TicketStatus, Story
│   │   ├── value_objects.py         # TicketId, Label, Priority
│   │   └── ports.py                 # TicketSource (protocol)
│   │
│   ├── memory/                      # Bounded Context: Agent Memory
│   │   ├── __init__.py
│   │   ├── entities.py              # MemoryEntry, Retrospective
│   │   ├── value_objects.py         # Category, ProjectScope
│   │   ├── ports.py                 # MemoryStore (protocol)
│   │   └── services.py             # RetrospectiveRunner, MemoryCompactor
│   │
│   ├── reporting/                   # Bounded Context: Reports & Dashboard
│   │   ├── __init__.py
│   │   ├── entities.py              # DemoReport, Artifact, QualityGate
│   │   ├── value_objects.py         # Screenshot, VideoRecording, DiffHighlight
│   │   ├── ports.py                 # ArtifactStore, ReportRepository, Recorder
│   │   └── services.py             # ReportGenerator, ArtifactCollector
│   │
│   ├── chat/                        # Bounded Context: Communication
│   │   ├── __init__.py
│   │   ├── entities.py              # Persona, Intent, Conversation
│   │   ├── value_objects.py         # MessageText, ActionId, ChannelId
│   │   ├── ports.py                 # ChatAdapter, NLUEngine (protocols)
│   │   └── services.py             # IntentRouter, PersonaManager
│   │
│   └── scheduling/                  # Bounded Context: Scheduling
│       ├── __init__.py
│       ├── entities.py              # Schedule, ScheduledJob
│       ├── value_objects.py         # CronExpression, Trigger
│       ├── ports.py                 # Scheduler, JobQueue (protocols)
│       └── services.py             # ScheduleManager
│
├── application/                     # Use cases — orchestrate domain objects
│   ├── __init__.py
│   │
│   ├── commands/                    # Write operations (CQRS command side)
│   │   ├── __init__.py
│   │   ├── run_cycle.py             # RunCycleCommand, RunCycleHandler
│   │   ├── create_project.py        # CreateProjectCommand
│   │   ├── approve_stories.py       # ApproveStoriesCommand
│   │   ├── trigger_improvement.py   # TriggerImprovementScanCommand
│   │   ├── schedule_cycle.py        # ScheduleCycleCommand
│   │   └── handle_webhook.py        # HandleWebhookCommand
│   │
│   ├── queries/                     # Read operations (CQRS query side)
│   │   ├── __init__.py
│   │   ├── get_cycle_status.py      # GetCycleStatusQuery
│   │   ├── get_report.py            # GetReportQuery, GetReportHistoryQuery
│   │   ├── get_plan.py              # GetDailyPlanQuery
│   │   ├── list_projects.py         # ListProjectsQuery
│   │   ├── list_issues.py           # ListIssuesQuery
│   │   └── get_dashboard.py         # GetDashboardStateQuery
│   │
│   ├── events/                      # Domain event handlers
│   │   ├── __init__.py
│   │   ├── bus.py                   # EventBus (in-process pub/sub)
│   │   ├── on_cycle_started.py      # Notify chat, update dashboard
│   │   ├── on_phase_changed.py      # Update live activity feed
│   │   ├── on_agent_activity.py     # Stream to SSE, log to DB
│   │   ├── on_cycle_completed.py    # Generate report, notify user
│   │   ├── on_pr_opened.py          # Track PR in dashboard
│   │   └── on_test_completed.py     # Record results, take screenshots
│   │
│   └── dto.py                       # Data transfer objects for all layers
│
├── infrastructure/                  # External adapters — implement domain ports
│   ├── __init__.py
│   │
│   ├── llm/                         # LLM backends
│   │   ├── __init__.py
│   │   ├── anthropic_adapter.py     # Claude API (implements LLMPort)
│   │   └── ollama_adapter.py        # Ollama local (implements LLMPort)
│   │
│   ├── vcs/                         # Version control systems
│   │   ├── __init__.py
│   │   ├── github_adapter.py        # PyGithub (implements VCSPort)
│   │   ├── gitlab_adapter.py        # GitLab API (future)
│   │   ├── git_cli.py               # Local git subprocess operations
│   │   └── framework_detector.py    # Auto-detect project framework
│   │
│   ├── tickets/                     # Ticket source adapters
│   │   ├── __init__.py
│   │   ├── github_tickets.py        # GitHub Issues (implements TicketPort)
│   │   ├── jira_tickets.py          # Jira (implements TicketPort)
│   │   ├── linear_tickets.py        # Linear (implements TicketPort)
│   │   └── gitlab_tickets.py        # GitLab Issues (implements TicketPort)
│   │
│   ├── chat/                        # Chat platform adapters
│   │   ├── __init__.py
│   │   ├── mattermost_adapter.py    # Mattermost (implements ChatAdapter)
│   │   ├── slack_adapter.py         # Slack (future, implements ChatAdapter)
│   │   └── keyword_nlu.py           # Simple keyword NLU (implements NLUEngine)
│   │
│   ├── recording/                   # Screenshot and video capture
│   │   ├── __init__.py
│   │   ├── playwright_recorder.py   # Playwright screenshots + video
│   │   └── artifact_store.py        # Local filesystem artifact storage
│   │
│   ├── persistence/                 # Data storage
│   │   ├── __init__.py
│   │   ├── sqlite_repos.py          # SQLite repos (projects, cycles, reports)
│   │   ├── memory_jsonl.py          # JSONL memory store (implements MemoryStore)
│   │   └── migrations/              # DB schema migrations
│   │       ├── __init__.py
│   │       └── v001_initial.py
│   │
│   ├── scheduling/                  # Scheduling backends
│   │   ├── __init__.py
│   │   └── apscheduler_adapter.py   # APScheduler (implements Scheduler)
│   │
│   └── config/                      # Configuration loading
│       ├── __init__.py
│       ├── yaml_loader.py           # YAML + env var merging
│       └── settings.py              # Pydantic settings models
│
├── presentation/                    # User interfaces
│   ├── __init__.py
│   │
│   ├── web/                         # Web application (FastAPI + HTMX)
│   │   ├── __init__.py
│   │   ├── app.py                   # FastAPI app factory
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── dashboard.py         # GET /dashboard — live activity
│   │   │   ├── projects.py          # CRUD /projects
│   │   │   ├── cycles.py            # GET/POST /cycles
│   │   │   ├── reports.py           # GET /reports, /reports/{id}
│   │   │   ├── health.py            # GET /health
│   │   │   ├── webhooks.py          # POST /webhooks/github, /webhooks/mattermost
│   │   │   └── api.py               # REST API for external consumers
│   │   ├── sse.py                   # Server-Sent Events for live updates
│   │   ├── templates/               # Jinja2 + HTMX templates
│   │   │   ├── base.html            # Layout with nav, theme, SSE connection
│   │   │   ├── dashboard.html       # Live agent activity feed
│   │   │   ├── projects/
│   │   │   │   ├── list.html        # Project cards with health badges
│   │   │   │   ├── detail.html      # Project overview, metrics, trends
│   │   │   │   └── create.html      # Add project form
│   │   │   ├── cycles/
│   │   │   │   ├── list.html        # Cycle history table
│   │   │   │   ├── detail.html      # Cycle timeline replay
│   │   │   │   └── live.html        # Live cycle progress (SSE-powered)
│   │   │   ├── reports/
│   │   │   │   ├── list.html        # Report gallery with thumbnails
│   │   │   │   ├── detail.html      # Full demo report with media
│   │   │   │   └── components/
│   │   │   │       ├── screenshot.html
│   │   │   │       ├── video_player.html
│   │   │   │       ├── diff_viewer.html
│   │   │   │       └── quality_gates.html
│   │   │   └── partials/            # HTMX partials for live updates
│   │   │       ├── activity_item.html
│   │   │       ├── agent_status.html
│   │   │       ├── budget_bar.html
│   │   │       └── toast.html
│   │   └── static/
│   │       ├── css/
│   │       │   ├── tokens.css       # Design tokens
│   │       │   ├── dashboard.css    # Dashboard layout
│   │       │   └── reports.css      # Report viewer styles
│   │       ├── js/
│   │       │   ├── sse.js           # SSE client + reconnect
│   │       │   ├── timeline.js      # Cycle replay scrubber
│   │       │   └── video.js         # Video player controls
│   │       └── img/
│   │
│   ├── tui/                         # Terminal UI (Textual)
│   │   ├── __init__.py
│   │   ├── app.py                   # Main Textual App
│   │   ├── screens/
│   │   │   ├── __init__.py
│   │   │   ├── dashboard.py         # Live agent activity (main screen)
│   │   │   ├── projects.py          # Project list + detail
│   │   │   ├── cycle.py             # Cycle progress + timeline
│   │   │   ├── report.py            # Report viewer (text mode)
│   │   │   └── config.py            # Settings editor
│   │   ├── widgets/
│   │   │   ├── __init__.py
│   │   │   ├── agent_panel.py       # Agent status card (role, phase, action)
│   │   │   ├── activity_log.py      # Scrolling activity feed
│   │   │   ├── budget_bar.py        # Token budget progress bar
│   │   │   ├── project_card.py      # Project summary widget
│   │   │   ├── cycle_timeline.py    # ASCII timeline of cycle phases
│   │   │   └── diff_viewer.py       # Syntax-highlighted diff
│   │   └── styles/
│   │       └── theme.tcss           # Textual CSS theme
│   │
│   └── cli/                         # CLI commands (Click/Typer)
│       ├── __init__.py
│       ├── main.py                  # Entry point: theswarm [command]
│       ├── cycle.py                 # theswarm cycle [--project X]
│       ├── projects.py              # theswarm projects add/list/remove
│       ├── dashboard.py             # theswarm dashboard (launches TUI)
│       ├── serve.py                 # theswarm serve (launches web)
│       └── status.py                # theswarm status
│
├── __init__.py
└── __main__.py                      # Entry point: python -m theswarm
```

---

## Domain Layer — Key Entities and Ports

### Projects

```python
# domain/projects/entities.py

@dataclass(frozen=True)
class Project:
    id: str                         # slug: "swarm-todo-app"
    repo: RepoUrl                   # value object: "jrechet/swarm-todo-app"
    default_branch: str             # auto-detected or configured
    framework: Framework            # auto-detected: fastapi, django, next, generic
    ticket_source: str              # "github" | "jira" | "linear" | "gitlab"
    team_channel: str               # Mattermost channel for this project
    schedule: CronExpression | None # recurring cycle schedule
    max_daily_stories: int          # stories per cycle (default 3)
    token_budget: dict[str, int]    # per-role budget override
    test_command: str               # detected or explicit: "pytest tests/"
    source_dir: str                 # detected: "src/", "app/", "."
    created_at: datetime
```

```python
# domain/projects/ports.py

class ProjectRepository(Protocol):
    async def get(self, project_id: str) -> Project | None: ...
    async def list_all(self) -> list[Project]: ...
    async def save(self, project: Project) -> None: ...
    async def delete(self, project_id: str) -> None: ...

class FrameworkDetector(Protocol):
    async def detect(self, workspace_path: str) -> FrameworkInfo: ...
```

### Cycles

```python
# domain/cycles/entities.py

@dataclass
class Cycle:
    id: CycleId                     # UUID
    project_id: str
    status: CycleStatus             # pending, running, completed, failed
    started_at: datetime | None
    completed_at: datetime | None
    phases: list[PhaseExecution]     # ordered list of phase runs
    budget_used: dict[str, TokenUsage]
    total_cost_usd: float
    prs_opened: list[int]
    prs_merged: list[int]
    artifacts: list[ArtifactRef]    # screenshots, videos, diffs

@dataclass(frozen=True)
class PhaseExecution:
    phase: str                      # "morning", "dev_iter_3", "review", "qa"
    agent: str                      # "po", "techlead", "dev", "qa"
    started_at: datetime
    completed_at: datetime | None
    status: str                     # "running", "completed", "failed"
    tokens_used: int
    cost_usd: float
    summary: str                    # Human-readable summary of what happened
```

```python
# domain/cycles/ports.py

class CycleRepository(Protocol):
    async def get(self, cycle_id: CycleId) -> Cycle | None: ...
    async def list_by_project(self, project_id: str, limit: int = 30) -> list[Cycle]: ...
    async def save(self, cycle: Cycle) -> None: ...

class CycleEventEmitter(Protocol):
    async def emit(self, event: DomainEvent) -> None: ...
```

### Agents

```python
# domain/agents/ports.py

class LLMPort(Protocol):
    """Any LLM backend: Claude, Ollama, OpenAI."""
    async def generate(self, system: str, prompt: str, max_tokens: int = 8192) -> LLMResponse: ...

class VCSPort(Protocol):
    """Any version control system: GitHub, GitLab."""
    async def get_issues(self, labels: list[str]) -> list[dict]: ...
    async def create_issue(self, title: str, body: str, labels: list[str]) -> dict: ...
    async def get_pull_requests(self, state: str = "open") -> list[dict]: ...
    async def create_pull_request(self, title: str, body: str, head: str, base: str) -> dict: ...
    async def submit_review(self, pr_number: int, body: str, event: str) -> None: ...
    async def merge_pr(self, pr_number: int, method: str = "squash") -> None: ...
    async def read_file(self, path: str, ref: str | None = None) -> str | None: ...
    async def update_file(self, path: str, content: str, message: str, branch: str) -> None: ...

class TicketPort(Protocol):
    """Any ticket source: GitHub, Jira, Linear, GitLab."""
    async def get_backlog(self) -> list[Ticket]: ...
    async def get_in_progress(self) -> list[Ticket]: ...
    async def transition(self, ticket_id: str, to_status: TicketStatus) -> None: ...
    async def create(self, title: str, body: str, labels: list[str]) -> Ticket: ...
```

### Reporting

```python
# domain/reporting/entities.py

@dataclass
class DemoReport:
    id: str
    cycle_id: CycleId
    project_id: str
    created_at: datetime
    summary: ReportSummary
    stories: list[StoryReport]      # per-story with screenshots, video, diff
    quality_gates: QualityGates     # test results, coverage, security
    agent_learnings: list[str]
    artifacts: list[Artifact]

@dataclass(frozen=True)
class Artifact:
    type: str                       # "screenshot", "video", "diff", "log"
    label: str                      # "before_login", "after_oauth", "e2e_recording"
    path: str                       # Relative path in artifact store
    mime_type: str
    size_bytes: int
    created_at: datetime

@dataclass(frozen=True)
class StoryReport:
    ticket_id: str
    title: str
    status: str                     # "completed", "in_progress", "blocked"
    pr_number: int | None
    files_changed: int
    lines_added: int
    lines_removed: int
    screenshots_before: list[Artifact]
    screenshots_after: list[Artifact]
    video: Artifact | None          # E2E test recording
    diff_highlights: list[DiffHighlight]
```

```python
# domain/reporting/ports.py

class Recorder(Protocol):
    """Captures visual artifacts during QA."""
    async def screenshot(self, url: str, label: str) -> Artifact: ...
    async def start_recording(self, url: str) -> None: ...
    async def stop_recording(self) -> Artifact: ...
    async def capture_before_after(self, url: str, branch_before: str, branch_after: str, label: str) -> tuple[Artifact, Artifact]: ...

class ArtifactStore(Protocol):
    async def save(self, cycle_id: CycleId, artifact: Artifact, data: bytes) -> str: ...
    async def get_url(self, path: str) -> str: ...
    async def list_by_cycle(self, cycle_id: CycleId) -> list[Artifact]: ...

class ReportRepository(Protocol):
    async def save(self, report: DemoReport) -> None: ...
    async def get(self, report_id: str) -> DemoReport | None: ...
    async def list_by_project(self, project_id: str, limit: int = 30) -> list[DemoReport]: ...
```

---

## Event Bus — The Nervous System

Everything flows through domain events. Both TUI and Web subscribe to the same stream.

```python
# application/events/bus.py

class EventBus:
    """In-process pub/sub for domain events."""

    def subscribe(self, event_type: type[DomainEvent], handler: Callable) -> None: ...
    async def publish(self, event: DomainEvent) -> None: ...

# domain/cycles/events.py

@dataclass(frozen=True)
class CycleStarted(DomainEvent):
    cycle_id: CycleId
    project_id: str
    triggered_by: str               # "user:jre", "schedule:daily", "webhook:push"

@dataclass(frozen=True)
class AgentActivityEvent(DomainEvent):
    cycle_id: CycleId
    project_id: str
    agent: str                      # "po", "techlead", "dev", "qa"
    action: str                     # "picking_task", "coding", "reviewing", "testing"
    detail: str                     # "Implementing US-012: Add OAuth2 flow"
    metadata: dict                  # pr_number, file_count, test_results, etc.

@dataclass(frozen=True)
class ArtifactCaptured(DomainEvent):
    cycle_id: CycleId
    artifact: Artifact

@dataclass(frozen=True)
class CycleCompleted(DomainEvent):
    cycle_id: CycleId
    project_id: str
    result: CycleResult
    report_id: str
```

The TUI subscribes via in-process callbacks. The web dashboard subscribes via SSE.

---

## TUI Design (Textual)

```
┌─ TheSwarm ──────────────────────────────────────────────── ⚙ ─┐
│                                                                │
│  ┌─ Agents ────────────────────────────────────────────────┐  │
│  │  🟢 PO        │ 🟡 TechLead   │ 🔴 Dev       │ ⚪ QA  │  │
│  │  Idle         │ Reviewing #47 │ Coding US-012│ Wait   │  │
│  │               │ 2m 14s        │ iter 3/5     │        │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌─ Activity ──────────────────────────────── swarm-todo ▼ ┐  │
│  │  12:34  Dev    Writing src/auth/middleware.ts            │  │
│  │  12:33  Dev    Tests: 12/14 passing — 2 failures        │  │
│  │  12:31  TL     ✅ Approved PR #46 → squash merged       │  │
│  │  12:28  TL     Reviewing PR #46: +142 -23 lines         │  │
│  │  12:25  Dev    Opened PR #46: "Add OAuth2 flow"         │  │
│  │  12:20  Dev    Running pytest... 14/14 passing          │  │
│  │  12:15  Dev    Implementing US-011: OAuth2 integration  │  │
│  │  12:10  TL     Broke US-009 into 3 dev tasks            │  │
│  │  12:05  PO     Selected 3 stories for today             │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌─ Budget ────────────┐  ┌─ Today ──────────────────────┐   │
│  │ PO   ██░░░ 23%      │  │ ✅ US-010: Fix redirect      │   │
│  │ TL   ████░ 61%      │  │ 🔄 US-011: OAuth2 flow       │   │
│  │ Dev  ██████░ 78%    │  │ ⬚ US-012: Dashboard metrics  │   │
│  │ QA   ░░░░░ 0%       │  │                              │   │
│  │ Cost: $4.20         │  │ PRs: 2 open, 1 merged        │   │
│  └──────────────────────┘  └──────────────────────────────┘   │
│                                                                │
│  [P]rojects  [C]ycle  [R]eports  [S]ettings  [Q]uit          │
└────────────────────────────────────────────────────────────────┘
```

**Screens:**
- **Dashboard** (default) — live agent activity, budget, today's plan
- **Projects** — list/add/configure projects, health status
- **Cycle** — start a cycle, view progress, timeline replay
- **Reports** — browse reports, view text-mode summaries with diffs
- **Settings** — edit config, manage schedules

**Key bindings:**
- `p` — projects, `c` — cycle, `r` — reports, `s` — settings, `q` — quit
- `Tab` — cycle focus between panels
- `Enter` — drill into selected item
- `g` — trigger "go" (start cycle on selected project)
- `/` — search/filter activity log

---

## Web Dashboard Design (FastAPI + HTMX)

HTMX gives us SPA-like interactivity with server-rendered HTML. No React/Vue build step.

**Pages:**

| Route | Template | Description |
|-------|----------|-------------|
| `/` | `dashboard.html` | Live activity feed, agent status cards, SSE-powered |
| `/projects` | `projects/list.html` | Grid of project cards with health badges |
| `/projects/{id}` | `projects/detail.html` | Project metrics, recent cycles, config |
| `/projects/new` | `projects/create.html` | Add project form (auto-detects framework) |
| `/cycles` | `cycles/list.html` | Cycle history with filters |
| `/cycles/{id}` | `cycles/detail.html` | Cycle timeline with phase replay |
| `/cycles/{id}/live` | `cycles/live.html` | Live cycle view (SSE) |
| `/reports` | `reports/list.html` | Report gallery with screenshot thumbnails |
| `/reports/{id}` | `reports/detail.html` | Full demo report with screenshots/video |
| `/health` | JSON | System health check |
| `/api/...` | JSON | REST API for external consumers and TUI |

**HTMX Patterns:**
- Activity feed: `hx-sse="connect:/sse/activities"` — auto-appends new items
- Agent status: `hx-sse="connect:/sse/agents"` — swaps status badges live
- Budget bars: `hx-get="/partials/budget" hx-trigger="every 5s"` — polls budget
- Cycle trigger: `hx-post="/cycles" hx-target="#cycle-status"` — starts cycle inline
- Report approval: `hx-post="/reports/{id}/approve" hx-swap="outerHTML"` — approves inline

**Visual Design:**
- Dark theme by default (dev tool aesthetic)
- Light theme available
- Monospace activity log, proportional text for reports
- Screenshot grid with lightbox zoom
- Video player with playback controls
- Syntax-highlighted diff viewer
- Responsive (works on phone for checking status)

---

## Demo Report: Screenshot & Video Capture

### How It Works

**During QA phase:**

1. **Before screenshots**: QA checks out `main` branch, starts app, takes screenshots of key pages
2. **After screenshots**: QA checks out PR branch, restarts app, takes same screenshots
3. **E2E recording**: Playwright records video during E2E test execution
4. **Diff highlights**: Extract key hunks from PR diff, annotate with context

```python
# infrastructure/recording/playwright_recorder.py

class PlaywrightRecorder:
    """Captures screenshots and video using Playwright."""

    async def screenshot(self, url: str, label: str, viewport: tuple = (1280, 720)) -> Artifact:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport_size={"width": viewport[0], "height": viewport[1]})
            await page.goto(url, wait_until="networkidle")
            path = self._artifact_path(label, "png")
            await page.screenshot(path=path, full_page=True)
            await browser.close()
            return Artifact(type="screenshot", label=label, path=path, ...)

    async def record_e2e(self, url: str, test_fn: Callable) -> Artifact:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context(record_video_dir=self._video_dir)
            page = await context.new_page()
            await test_fn(page)  # Run the E2E test
            await context.close()
            video_path = await page.video.path()
            return Artifact(type="video", label="e2e_recording", path=video_path, ...)

    async def capture_before_after(self, base_url: str, workspace: str, pr_branch: str, label: str):
        # 1. Screenshot on main
        before = await self.screenshot(base_url, f"{label}_before")
        # 2. Checkout PR branch, restart app
        await _run_git("checkout", pr_branch, cwd=workspace)
        await self._restart_app(workspace)
        # 3. Screenshot on PR branch
        after = await self.screenshot(base_url, f"{label}_after")
        return before, after
```

### Artifact Storage

```
.swarm-workspaces/{project}/artifacts/
├── cycle-{uuid}/
│   ├── screenshots/
│   │   ├── us011_before_login.png
│   │   ├── us011_after_login.png
│   │   ├── us011_before_dashboard.png
│   │   └── us011_after_dashboard.png
│   ├── videos/
│   │   ├── e2e_oauth_flow.webm
│   │   └── e2e_dashboard_load.webm
│   ├── diffs/
│   │   ├── pr46_highlights.html
│   │   └── pr47_highlights.html
│   └── report.json                  # Full report metadata
```

Served by FastAPI `StaticFiles` mount at `/artifacts/`.

---

## Persistence: SQLite

Single SQLite database replaces all in-memory state. Survives restarts.

```sql
-- Projects
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    default_branch TEXT DEFAULT 'main',
    framework TEXT DEFAULT 'generic',
    ticket_source TEXT DEFAULT 'github',
    team_channel TEXT DEFAULT '',
    schedule TEXT DEFAULT '',
    config_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Cycles
CREATE TABLE cycles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    status TEXT NOT NULL DEFAULT 'pending',
    triggered_by TEXT DEFAULT '',
    started_at TEXT,
    completed_at TEXT,
    total_tokens INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0,
    prs_opened TEXT DEFAULT '[]',
    prs_merged TEXT DEFAULT '[]',
    result_json TEXT DEFAULT '{}',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Agent activities (event log)
CREATE TABLE activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL REFERENCES cycles(id),
    project_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Demo reports
CREATE TABLE reports (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL REFERENCES cycles(id),
    project_id TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    stories_json TEXT NOT NULL,
    quality_json TEXT NOT NULL,
    learnings_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);

-- Artifacts (screenshots, videos, diffs)
CREATE TABLE artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL REFERENCES cycles(id),
    report_id TEXT REFERENCES reports(id),
    story_id TEXT DEFAULT '',
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Schedules
CREATE TABLE schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id),
    cron_expression TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    last_run TEXT,
    next_run TEXT,
    created_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX idx_cycles_project ON cycles(project_id, started_at DESC);
CREATE INDEX idx_activities_cycle ON activities(cycle_id, created_at);
CREATE INDEX idx_reports_project ON reports(project_id, created_at DESC);
CREATE INDEX idx_artifacts_cycle ON artifacts(cycle_id);
```

---

## Migration Strategy

We can't rewrite everything at once. Incremental migration over 10 sessions.

### Session 1-2: Skeleton + Domain Layer
- Create full directory structure
- Write domain entities, value objects, ports (all pure Python, no deps)
- Write event bus
- Write SQLite persistence layer
- Tests for all domain logic

### Session 3-4: Application Layer + Migrate Agents
- Write use cases (commands + queries)
- Migrate existing agents to use domain ports instead of direct imports
- Wire ticket source adapters through TicketPort
- Existing tests keep passing via backward-compat shim

### Session 5-6: Web Dashboard
- FastAPI app with HTMX templates
- Live activity feed via SSE
- Project management CRUD
- Report viewer with placeholder artifacts
- Static file serving for screenshots/video

### Session 7: TUI
- Textual app with all screens
- Shares application layer with web
- Widget library: agent panels, activity log, budget bars, diff viewer
- Keyboard navigation

### Session 8: Recording & Rich Reports
- Playwright recorder integration
- Before/after screenshots
- E2E video capture
- Report generator with embedded media
- Mattermost rich report notifications

### Session 9: Scheduling + Self-Improvement
- APScheduler integration
- GitHub webhook endpoints
- Improver agent
- Cross-project memory

### Session 10: Polish + Production
- Startup validation
- Error recovery / checkpoints
- English-first i18n
- DM onboarding flow
- CI/CD updates
- Documentation

---

## Dependencies to Add

```toml
[project.dependencies]
# Existing deps stay...

# New for v2.0
textual = ">=0.80"           # TUI framework
jinja2 = ">=3.1"             # Web templates
python-multipart = ">=0.0.9" # Form uploads (already present)
apscheduler = ">=3.10"       # Cron scheduling
playwright = ">=1.40"        # Screenshots + video
rich = ">=13.0"              # Rich terminal output (Textual dep)
```

---

## Key Design Decisions

1. **HTMX over React/Vue** — Server-rendered, no build step, no node_modules, works with Python templates. HTMX + SSE gives us real-time updates without a JS framework. The product is for devs who appreciate simplicity.

2. **Textual for TUI** — Python-native, CSS-like styling, rich widget library, async-first. Shares the same application layer as the web app. Can run over SSH.

3. **SQLite over Postgres** — Single-file database, zero ops, survives restarts, fast enough for this workload. Can migrate to Postgres later if needed (repository pattern makes it swappable).

4. **Event bus over direct calls** — Decouples agents from presentation. Both TUI and web subscribe to the same domain events. Adding a new frontend (Slack bot, Discord bot) just means adding another subscriber.

5. **Ports/Adapters over inheritance** — Every external system accessed through a Protocol. Swap GitHub for GitLab by writing one adapter. Swap Claude for Ollama same way. Tests mock the port, not the adapter.

6. **CQRS light** — Separate command and query paths. Commands mutate state and emit events. Queries read from SQLite. No event sourcing (overkill here), but the separation keeps the code clean.

---

## What This Enables

When v2.0 is done, a user can:

1. **Add a project**: `theswarm projects add jrechet/my-app` → auto-detects Python/FastAPI, sets up daily schedule
2. **Watch agents work**: Open TUI or web dashboard, see live activity as agents plan, code, review, test
3. **Browse demo reports**: Click through screenshots showing before/after for each story, watch E2E video recordings
4. **Manage multiple projects**: Each project has its own backlog, schedule, budget, team channel
5. **Get improvement suggestions**: Improver agent creates issues for tech debt, missing tests, outdated deps
6. **Use any ticket source**: GitHub Issues, Jira, Linear, or GitLab — per project
7. **Schedule cycles**: "Run every weekday at 8am on swarm-todo-app, every Monday on theswarm"
8. **Check from phone**: Responsive web dashboard works on mobile
9. **Check from terminal**: Full TUI over SSH, same data as web

That's the plan. Ready to build.
