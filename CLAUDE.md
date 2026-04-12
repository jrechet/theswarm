# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is TheSwarm

TheSwarm is an autonomous AI dev team that receives feature requests via Mattermost DMs and orchestrates a full development cycle: planning, implementation, code review, testing, and reporting. It operates as four specialized agents (PO, TechLead, Dev, QA) coordinated through LangGraph state graphs.

## Build & Run

```bash
# Install dependencies (uses uv, not pip)
uv sync --dev

# Run tests
uv run pytest tests/ -v --tb=short

# Run a single test
uv run pytest tests/test_cycle.py::test_stub_cycle_runs -v

# Start the server (default mode, listens on :8091)
uv run python -m theswarm

# CLI cycle modes (require SWARM_GITHUB_REPO env var)
uv run python -m theswarm --cycle           # full daily cycle
uv run python -m theswarm --dev-only        # dev agent only
uv run python -m theswarm --techlead-only   # techlead review only

# v2 CLI (Clean Architecture layer)
uv run python -m theswarm.presentation.cli.main serve          # web dashboard on :8091
uv run python -m theswarm.presentation.cli.main dashboard      # TUI dashboard
uv run python -m theswarm.presentation.cli.main projects list  # list registered projects
uv run python -m theswarm.presentation.cli.main projects add my-app owner/my-app
uv run python -m theswarm.presentation.cli.main cycle --project my-app
uv run python -m theswarm.presentation.cli.main schedule set my-app "0 8 * * 1-5"
uv run python -m theswarm.presentation.cli.main schedule list
uv run python -m theswarm.presentation.cli.main validate       # check env vars
uv run python -m theswarm.presentation.cli.main status

# Docker
docker compose up
```

## Architecture

### Two packages in `src/`

- **`theswarm`** — the autonomous dev team (agents, cycle orchestration, gateway)
- **`theswarm_common`** — shared infrastructure (Mattermost adapter, config loader, models) originally shared with a sibling `swarm-bots` platform project

### Clean Architecture / DDD Layer (v2)

The v2 architecture lives alongside the original code, organized as Clean Architecture with DDD:

```
src/theswarm/
├── domain/               # Frozen dataclasses, value objects, Protocol ports
│   ├── projects/         # Project entity, Framework/RepoUrl VOs
│   ├── cycles/           # Cycle entity, CycleId/Budget/PhaseExecution
│   ├── agents/           # AgentRole, AgentCapability
│   ├── tickets/          # Ticket entity, TicketStatus state machine
│   ├── memory/           # MemoryEntry, Retrospective, MemoryCategory
│   ├── reporting/        # DemoReport, StoryReport, Artifact, QualityGate
│   ├── scheduling/       # Schedule entity, CronExpression
│   └── chat/             # ChatMessage, Intent
├── application/          # CQRS commands/queries, DTOs, EventBus
│   ├── commands/         # CreateProject, RunCycle, ManageSchedule, etc.
│   ├── queries/          # ListProjects, GetDashboard, GetCycleStatus, etc.
│   ├── events/           # EventBus (in-process pub/sub)
│   ├── services/         # ReportGenerator, ImprovementEngine, StartupValidator
│   └── dto.py            # ProjectDTO, CycleDTO, DashboardDTO, ScheduleDTO
├── infrastructure/       # Adapters implementing domain ports
│   ├── persistence/      # SQLite repos (Project, Cycle, Schedule, Memory)
│   ├── recording/        # LocalArtifactStore, SQLiteReportRepository
│   ├── scheduling/       # CronScheduler, WebhookHandler
│   ├── tickets/          # GitHubTicketSource adapter
│   └── vcs/              # FrameworkDetector
└── presentation/         # User-facing layers
    ├── cli/              # argparse CLI (projects, cycles, schedules, validate)
    ├── web/              # FastAPI + HTMX + Jinja2 + SSE dashboard
    │   ├── routes/       # dashboard, projects, cycles, reports, webhooks, health, api
    │   ├── templates/    # Server-rendered HTML templates
    │   └── static/       # CSS design system, SSE client JS
    └── tui/              # Textual TUI (agent panels, budget bars, activity log)
```

### Agent pipeline (LangGraph StateGraph)

Each agent is a `StateGraph` compiled graph in `src/theswarm/agents/`. They share `AgentState` (a TypedDict in `config.py`) as their state schema.

**Daily cycle flow** (`cycle.py`):
1. **PO** (morning) — selects backlog issues, labels them `status:ready`, writes daily plan
2. **TechLead** (breakdown) — splits user stories into `role:dev` + `status:ready` sub-tasks
3. **Dev loop** (up to 5 iterations) — picks a `status:ready` task, calls Anthropic API to implement, runs tests, opens PR
4. **TechLead** (review_loop) — reviews PRs via Claude, approves/requests changes, merges approved PRs
5. **QA** — writes Playwright E2E tests, runs unit + E2E + semgrep security scan, generates demo report
6. **PO** (evening) — validates demo report, writes daily report

### Key components (original)

- **`gateway.py`** — FastAPI app, Mattermost callback handling, wires the PO persona, runs cycles
- **`persona.py`** — NLU-driven DM handler for `@swarm-po` (intent → action dispatch)
- **`memory.py`** — Appends structured learnings to `AGENT_MEMORY.md` in the target repo
- **`tools/claude.py`** — Anthropic Messages API wrapper (`ClaudeCLI`)
- **`tools/github.py`** — Async PyGithub wrapper (runs blocking calls in executor)
- **`tools/git.py`** — Local git CLI operations (clone, branch, commit, push)

### Key components (v2 Clean Architecture)

- **EventBus** — in-process pub/sub, wires domain events to SSE, TUI, and webhooks
- **SQLite persistence** — aiosqlite repos for projects, cycles, schedules, memory, reports
- **SSEHub** — fan-out broadcaster for real-time dashboard updates
- **CronScheduler** — asyncio tick-based scheduler with cron field matching
- **WebhookHandler** — GitHub webhook with HMAC-SHA256 verification
- **ImprovementEngine** — analyzes cycle reports, generates improvement suggestions
- **ReportGenerator** — builds DemoReport from Cycle with quality gates
- **StartupValidator** — fail-fast env var validation before running

### Issue label state machine

Issues flow through labels: `status:backlog` → `status:ready` → `status:in-progress` → `status:review` → merged/closed

### Stub mode

When `SWARM_GITHUB_REPO` is not set, all agents run in stub mode — they log what they would do but make no API calls. Tests use this mode.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API access (required for real mode) |
| `GITHUB_TOKEN` | PyGithub operations |
| `SWARM_GITHUB_REPO` | Default target repo (`owner/repo`) |
| `SWARM_PO_GITHUB_REPOS` | Comma-separated allowlist of repos |
| `SWARM_PO_MATTERMOST_TOKEN` | Mattermost bot token for @swarm-po |
| `MATTERMOST_BOT_TOKEN` | Shared Mattermost token |
| `EXTERNAL_URL` | Public URL for Mattermost callbacks |

## Config

`theswarm.yaml` holds defaults (Mattermost URLs, server config, agent settings). Env vars override YAML values. The `load_yaml_with_env()` function in `theswarm_common/config.py` handles the merge.

## Deployment

Docker Swarm + Traefik on a self-hosted runner. CI runs tests on push/PR, then triggers CD which builds a container image to GHCR and deploys via `docker stack up`. The container mounts the host's `.claude` config for Claude Code access.

## Testing conventions

- pytest with `asyncio_mode = "auto"` — async test functions work without decorators
- `respx` for HTTP mocking, `pytest-mock` for general mocking
- Tests in `tests/` directory, organized by layer:
  - `tests/domain/` — domain entity and value object tests (100% coverage target)
  - `tests/application/` — command handler, query, and service tests
  - `tests/infrastructure/` — SQLite repo, artifact store, scheduler, webhook tests
  - `tests/presentation/` — CLI, web app (httpx ASGI), TUI (Textual pilot) tests
  - `tests/integration/` — cross-layer end-to-end tests
  - `tests/test_*.py` — original agent and tool tests (flat structure)
- 860+ tests, all passing

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
