# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is TheSwarm

TheSwarm is an autonomous AI dev team that receives feature requests via Mattermost DMs and orchestrates a full development cycle: planning, implementation, code review, testing, and reporting. It operates as four specialized agents (PO, TechLead, Dev, QA) coordinated through LangGraph state graphs.

## Build & Run

```bash
# Install dependencies (uses uv, not pip)
uv sync --dev

# Run tests (excludes E2E — see below)
uv run pytest tests/ -v --tb=short --ignore=tests/e2e -p no:playwright

# Run a single test
uv run pytest tests/test_cycle.py::test_stub_cycle_runs -v

# Run E2E tests separately (requires running server)
uv run pytest tests/e2e/ -v --headed

# Start the unified server (web dashboard + Mattermost + GitHub, listens on :8091)
uv run python -m theswarm

# CLI commands
uv run python -m theswarm serve                                # explicit serve (same as no args)
uv run python -m theswarm serve --port 9000                    # custom port
uv run python -m theswarm projects list                        # list registered projects
uv run python -m theswarm projects add my-app owner/my-app     # register a project
uv run python -m theswarm projects remove my-app               # remove a project
uv run python -m theswarm cycle --project my-app               # run cycle for registered project
uv run python -m theswarm cycle --project my-app --autonomous  # run until all stories done
uv run python -m theswarm cycle --project my-app -a --max-cycles 5  # autonomous with cap
uv run python -m theswarm schedule set my-app "0 8 * * 1-5"   # set cron schedule
uv run python -m theswarm schedule list                        # list schedules
uv run python -m theswarm validate                             # check env vars
uv run python -m theswarm status                               # system status
uv run python -m theswarm dashboard                            # TUI dashboard

# Legacy cycle modes (require SWARM_GITHUB_REPO env var)
uv run python -m theswarm --cycle           # full daily cycle
uv run python -m theswarm --autonomous      # run cycles until all stories resolved
uv run python -m theswarm --dev-only        # dev agent only
uv run python -m theswarm --techlead-only   # techlead review only

# Docker
docker compose up
```

## Architecture

### Two packages in `src/`

- **`theswarm`** — the autonomous dev team (agents, cycle orchestration, gateway)
- **`theswarm_common`** — shared infrastructure (Mattermost adapter, config loader, models) originally shared with a sibling `swarm-bots` platform project

### Clean Architecture / DDD Layer

The architecture is organized as Clean Architecture with DDD. The unified server (`presentation/web/server.py`) starts the v2 web app and bridges in the original Mattermost/GitHub/persona integration via `GatewayBridge`:

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
5. **QA** — writes Playwright E2E tests, runs unit + E2E + semgrep security scan, captures demo screenshots via Playwright, generates demo report with artifacts
6. **PO** (evening) — validates demo report, writes daily report

**Autonomous mode** (`cycle.py:run_autonomous()`):
- Loops `run_daily_cycle()` until all user stories are resolved or max_cycles hit
- After each cycle, checks GitHub for remaining backlog/open PRs
- Continues past transient failures (rate limits, timeouts)
- CLI: `--autonomous` / `-a` flag

### Key components (original, bridged into v2)

- **`presentation/web/server.py`** — Unified server startup: creates v2 web app, connects Mattermost/GitHub, wires persona via `GatewayBridge`. Contains `_LlmNLU` (Haiku-powered intent classifier with keyword fast path)
- **`api.py`** — Headless cycle API: `CycleTracker` (in-memory), `run_api_cycle()` (executes real agent pipeline). Dashboard and cycle routes merge both SQLite and tracker data
- **`gateway/wiring.py`** — Event handlers for Mattermost button callbacks (story approval, ping/pong)
- **`persona.py`** — NLU-driven DM handler for `@swarm-po` (intent -> action dispatch)
- **`cycle.py`** — Orchestrates full daily cycle (PO -> TechLead -> Dev -> QA) and autonomous multi-cycle loop
- **`tools/claude.py`** — Anthropic Messages API wrapper (`ClaudeCLI`)
- **`tools/github.py`** — Async PyGithub wrapper (runs blocking calls in executor)
- **`tools/git.py`** — Local git CLI operations (clone, branch, commit, push)

### Key components (Clean Architecture layer)

- **EventBus** — in-process pub/sub, wires domain events to SSE, TUI, and webhooks
- **SQLite persistence** — aiosqlite repos for projects, cycles, schedules, memory, reports
- **SSEHub** — fan-out broadcaster for real-time dashboard updates
- **CronScheduler** — asyncio tick-based scheduler with cron field matching
- **WebhookHandler** — GitHub webhook with HMAC-SHA256 verification
- **ImprovementEngine** — analyzes cycle reports, generates improvement suggestions
- **ReportGenerator** — builds DemoReport from Cycle with quality gates
- **PlaywrightRecorder** — captures screenshots and videos of the running app during QA phase
- **LocalArtifactStore** — stores demo artifacts on disk at `~/.swarm-data/artifacts/{cycle_id}/`
- **Artifacts route** — serves stored screenshots/videos at `/artifacts/{path}`
- **StartupValidator** — fail-fast env var validation (runs at server boot)
- **GatewayBridge** — thin adapter connecting persona.py and wiring.py to the v2 web app

### Dev-plan phases (see `docs/dev-role-dashboard.md`)

Phases A–L are shipped (all green, ~2053 tests):

- **A — Codenames + three-layer memory** (portfolio × project × role, persona prompts).
- **B — Dashboard chat + HITL audit** (multi-role chat store, mentions, audit log).
- **C — PO intelligence** (proposals, OKRs, policy filter, digest, signals).
- **D — TechLead intelligence** (ADRs, debt register, dep radar, review calibration, second-opinion).
- **E — Dev rigour** (TDD artifacts, thoughts, self-review, refactor preflight, coverage deltas).
- **F — QA enrichments** (archetype mix, flake tracking, quarantines, quality gates, outcome cards).
- **G — Scout** (intel sources, feed items, cluster briefs).
- **H — Designer** (design tokens, component inventory, briefs, visual regression, anti-template audit).
- **I — Security + SRE** (threat models, data inventory, findings, SBOM, AuthZ; deployments, incidents, cost).
- **J — Analyst, Writer, Release** (metrics/instrumentation/observations; docs/quickstart/changelog; versions/flags/rollback).
- **K — Architect + Chief of Staff** (paved roads, portfolio ADRs, direction briefs; routing rules, budget policies, onboarding, archive).
- **L — Portfolio polish** (cross-project refactor programs, semantic memory, prompt library with audit, autonomy-spectrum config).

See `docs/ROLES-OVERVIEW.md` for the role-by-role dashboard surface map.

### Issue label state machine

Issues flow through labels: `status:backlog` → `status:ready` → `status:in-progress` → `status:review` → merged/closed

### Stub mode

When `SWARM_GITHUB_REPO` is not set, all agents run in stub mode — they log what they would do but make no API calls. Tests use this mode.

## Environment Variables

Secrets live in `.env` at the project root. Source before running:
```bash
set -a && source .env && set +a
```

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API access (required for real mode) |
| `GITHUB_TOKEN` | PyGithub operations |
| `SWARM_GITHUB_REPO` | Default target repo (`owner/repo`) |
| `SWARM_PO_GITHUB_REPOS` | Comma-separated allowlist of repos |
| `SWARM_PO_MATTERMOST_TOKEN` | Mattermost bot token for @swarm-po |
| `MATTERMOST_BOT_TOKEN` | Shared Mattermost token |
| `EXTERNAL_URL` | Public URL for Mattermost callbacks |
| `BASE_PATH` | URL prefix for reverse proxy (e.g. `/swarm`). All templates use `{{ base }}` |
| `SEQ_URL` | Seq log aggregation endpoint (optional, CLEF format) |
| `SEQ_API_KEY` | Seq API key (optional) |

## Reverse proxy (BASE_PATH)

In production, Traefik routes `/swarm/*` to the app and strips the prefix. The app uses `BASE_PATH=/swarm` so templates render correct URLs. All template links, form actions, static assets, and SSE connections use `{{ base }}` prefix. JS reads it from `document.documentElement.dataset.base`.

## Config

`theswarm.yaml` holds defaults (Mattermost URLs, server config, agent settings). Env vars override YAML values. The `load_yaml_with_env()` function in `theswarm_common/config.py` handles the merge.

## Deployment

Docker Swarm + Traefik on a self-hosted runner. CI runs tests on push/PR, then triggers CD which builds a container image to GHCR and deploys via `docker stack up`. The container mounts the host's `.claude` config for Claude Code access.

## Testing conventions

- pytest with `asyncio_mode = "auto"` — async test functions work without decorators
- `respx` for HTTP mocking, `pytest-mock` for general mocking
- **E2E tests must run separately** — pytest-playwright's sync fixtures conflict with pytest-asyncio's event loop. CI uses `--ignore=tests/e2e -p no:playwright`
- Tests in `tests/` directory, organized by layer:
  - `tests/domain/` — domain entity and value object tests (100% coverage target)
  - `tests/application/` — command handler, query, and service tests
  - `tests/infrastructure/` — SQLite repo, artifact store, scheduler, webhook tests
  - `tests/presentation/` — CLI, web app (httpx ASGI), TUI (Textual pilot) tests
  - `tests/integration/` — cross-layer end-to-end tests
  - `tests/e2e/` — Playwright browser tests (run separately, need running server)
  - `tests/test_*.py` — original agent and tool tests (flat structure)
- 2103+ tests, all passing