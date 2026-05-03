# TheSwarm

**Autonomous multi-role AI dev team.** You describe a sprint in plain English. A staffed swarm of role-specialised agents — PO, TechLead, Dev, QA, Architect, Chief of Staff, Scout, Designer, Security, SRE, Analyst, Writer, Release — plans it, builds it, reviews it, tests it, and ships it. Every action is logged, gated by per-role autonomy levels, and visible in a real-time dashboard.

```
plain-English sprint  →  PO drafts issues  →  TechLead breaks down  →  Dev opens PRs
                                ↓                                          ↓
                          OKRs · ADRs · paved-road rules                TechLead reviews + merges
                                ↓                                          ↓
                          Memory · Prompt library · Audit trail        QA: e2e + security + demo
                                                                            ↓
                                                                     PO validates · Report shipped
```

---

## Features

### Role-specialised agents (LangGraph state graphs)

| Role | Owns | Surface |
|------|------|---------|
| **PO** | Outcome framing, backlog, OKRs, policy, signals, digest | `/proposals`, `/projects/{id}/okrs` |
| **TechLead** | ADRs, debt register, dep radar, review verdicts, second-opinion | `/projects/{id}/adrs`, `/debt`, `/deps` |
| **Dev** | TDD artifacts, dev thoughts, refactor preflight, self-review, coverage delta | `/projects/{id}/dev/tdd`, `/dev/thoughts`, `/dev/preflight` |
| **QA** | Test plans, archetype mix, flake log, quarantines, quality gates, outcome cards | `/projects/{id}/qa/plans`, `/qa/flakes`, `/qa/quarantine` |
| **Designer** | Tokens, component inventory, briefs, visual regression, anti-template audit | `/designer/...` |
| **Security** | Threat models, data inventory, findings, SBOM, AuthZ matrix | `/security/...` |
| **SRE** | Deployments, incidents, cost tracking | `/sre/...` |
| **Analyst** | Metric definitions, instrumentation plans, outcome observations | `/analyst/...` |
| **Writer** | Doc artifacts, quickstart checks, changelog | `/writer/...` |
| **Release** | Versions, feature flags, rollback actions | `/release/...` |
| **Architect** *(portfolio)* | Paved-road rules, portfolio ADRs, direction briefs | `/architect/paved-road`, `/architect/adrs`, `/architect/briefs` |
| **Chief of Staff** *(portfolio)* | Routing rules, budget policies, onboarding, archive | `/chief-of-staff/routing`, `/budgets`, `/archive` |
| **Scout** *(portfolio)* | External intel ingest (CVEs, releases, papers, competitors), clustered into briefs | `/intel/feed`, `/intel/sources`, `/intel/clusters` |

### Portfolio knowledge surfaces

- **Refactor programs** (`/refactor-programs`) — coordinate refactors across multiple projects (proposed → active → completed); opt-in per project.
- **Semantic memory** (`/semantic-memory`, `/projects/{id}/semantic-memory`) — opt-in retrieval-friendly notes with tag + substring search; portfolio-wide and per-project.
- **Prompt library** (`/prompt-library`, `/prompt-library/audit`) — versioned prompts with full create/update/deprecate/restore audit trail.
- **Three-layer memory** — portfolio × project × role; persona prompts inject role-scoped memory at every agent call.

### Autonomy spectrum

Per-(project, role) gating:

| Level | Behaviour |
|-------|-----------|
| `manual` | Human-initiated only. Agent does not act. |
| `assisted` | Agent proposes; human confirms every step. |
| `supervised` | Agent acts; human reviews before merge. |
| `autonomous` | Agent acts and ships unless blocked. |

Defaults are conservative. Override per project at `/projects/{id}/autonomy`. Higher autonomy is opt-in because every action is logged and irreversible.

### Cycle pipeline

1. **PO morning** — picks `status:backlog` issues, labels `status:ready`, writes daily plan.
2. **TechLead breakdown** — splits user stories into `role:dev` sub-tasks.
3. **Dev loop** (≤ 5 iters) — picks a `status:ready` task, calls Anthropic, runs tests, opens PR.
4. **TechLead review_loop** — Claude review → approve/request-changes; merges approved PRs.
5. **QA** — Playwright E2E, unit tests, semgrep scan, demo screenshots, demo report with quality gates.
6. **PO evening** — validates demo report, writes daily report.

**Autonomous mode** loops `run_daily_cycle()` until all user stories resolved (or `--max-cycles` hit). Continues past transient failures (rate limits, timeouts).

### Resilience features (Sprint G)

- **Per-phase hard timeouts** — a hung agent cannot brick a cycle.
- **One-retry on transient Dev errors** + orphan cycle reaper (leaves stale state clean).
- **Circuit-breaker** on GitHub client (sprint G demo).
- **Pre-flight `/health/ready`** — clicking *Run cycle* checks Claude CLI, GitHub, repo permissions before launching.
- **Cancel button** on running cycles.
- **Tight CLI timeouts** — prevent runaway `claude` spawn.

### Platform features

| Phase | Feature | Purpose |
|-------|---------|---------|
| 1 | Hashline Edit Tool | Hash-anchored file editing prevents stale-line errors. |
| 1 | Ralph Loop | Persistent retry loop when quality gates fail. |
| 1 | Todo Enforcer Watchdog | Idle agent detection with configurable threshold + escalation. |
| 2 | Context Condensation | LLM-powered context summarisation using Haiku. |
| 2 | AGENTS.md Generator | Auto-generates docs by introspecting agent graphs. |
| 2 | Skill-Embedded MCPs | Mount/unmount skill manifests per task category. |
| 2 | Model Routing Table | Task category → model (Haiku for cheap, Sonnet for code). |
| 2 | IntentGate (Haiku NLU) | Param extraction with keyword fast path. |
| 3 | Sandbox Protocol | Pluggable execution backend (local, Docker, OpenHands). |
| 3 | AST-Grep Tool | Structural code search via `ast-grep` CLI wrapper. |

### Dashboard

- **Workspace** — Dashboard, Projects, Team
- **Activity** — Cycles (full history with cost, status, PRs), Chat (per `(project, codename)` thread, `@Codename` mentions), Proposals inbox
- **Output** — Reports, Demos (bento grid + A vs B compare), Features
- **Roles** — every role's surface (Architect, Chief of Staff, Scout, Product, TechLead, Dev rigour, QA, Designer, Security, SRE, Analyst, Writer, Release)
- **Knowledge** — Refactor programs, Semantic memory, Prompt library
- **System** — Health, Diagnostics, Autonomy config

Live updates via SSE. **Sprint composer** on every project page: describe the next sprint in plain English, the PO drafts backlog issues for review.

### Integrations

- **Mattermost** — `@swarm-po` DM bot with intent classifier (Haiku NLU), interactive button callbacks for story approval.
- **GitHub** — async PyGithub wrapper, webhook handler with HMAC-SHA256 verification, label-driven state machine.
- **Anthropic** — Claude CLI (subscription) preferred over API credits; falls back to Messages API. Per-phase model routing.
- **Seq** — CLEF-formatted logs at `SEQ_URL` for production observability.

---

## Quickstart

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- `ANTHROPIC_API_KEY` (or Claude CLI subscription)
- `GITHUB_TOKEN` for real mode (stub mode works without)

### Install

```bash
git clone https://github.com/jrechet/theswarm.git
cd theswarm
uv sync --dev
```

### Configure

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
SWARM_GITHUB_REPO=owner/my-app

# Optional
SWARM_PO_MATTERMOST_TOKEN=...
MATTERMOST_BOT_TOKEN=...
EXTERNAL_URL=https://your-domain.com
BASE_PATH=/swarm           # if behind a reverse proxy that strips a prefix
SEQ_URL=https://logs.example.com
SEQ_API_KEY=...
```

```bash
uv run python -m theswarm validate    # check env before starting
```

### Start

```bash
uv run python -m theswarm             # unified server on :8091
```

Dashboard: `http://localhost:8091/` (or `http://localhost:8091/swarm/` if `BASE_PATH=/swarm`).

### First sprint

1. Open dashboard → **+ Add Project** → enter `owner/repo`.
2. Click into the project → describe a sprint in the composer ("Add a venue capacity field to Venue, expose on GET API, write tests").
3. Click **Draft issues** → PO generates user stories → review.
4. Click **Run Cycle** → PO/TechLead/Dev/QA execute end-to-end.
5. Watch live progress on Cycles page; review demo report on Reports page when done.

### Stub mode

`SWARM_GITHUB_REPO` unset → all agents log what they *would* do without API calls. Perfect for testing the pipeline locally.

---

## CLI reference

```bash
# Server
python -m theswarm                                  # serve (default)
python -m theswarm serve --port 9000                # custom port
python -m theswarm validate                         # env check
python -m theswarm status                           # registered projects + active cycles
python -m theswarm dashboard                        # Textual TUI

# Projects
python -m theswarm projects list
python -m theswarm projects add my-app owner/my-app [--framework fastapi]
python -m theswarm projects remove my-app

# Cycles
python -m theswarm cycle --project my-app
python -m theswarm cycle --project my-app --autonomous
python -m theswarm cycle --project my-app -a --max-cycles 5

# Schedules (cron-driven autonomous cycles)
python -m theswarm schedule set my-app "0 8 * * 1-5"
python -m theswarm schedule list
python -m theswarm schedule disable my-app
python -m theswarm schedule delete my-app

# Legacy (single SWARM_GITHUB_REPO)
python -m theswarm --cycle
python -m theswarm --autonomous
python -m theswarm --dev-only
python -m theswarm --techlead-only
```

---

## Chat interface (Mattermost)

DM `@swarm-po`:

| Message | What happens |
|---------|--------------|
| Plain feature description | Generates user stories, asks for approval |
| `go` / `start` / `lance` | Launches a cycle on the default repo |
| `go on owner/repo` | Launches a cycle on a specific repo |
| `status` | Is a cycle running? |
| `plan` / `plan du jour` | Today's daily plan |
| `rapport` / `report` | Latest daily report |
| `backlog` / `issues` | Open GitHub issues |
| `repos` | Allowed repositories |
| `ping` | Tests interactive button callbacks |
| `help` | Help message |

Channel commands (any channel): `!swarm-po status`, `!swarm-po plan`, `!swarm-po report`.

In the dashboard chat, `@Codename` to address a specific agent in a project thread.

---

## Headless API

```bash
# Start a cycle
curl -X POST http://localhost:8091/api/cycle \
  -H "Content-Type: application/json" \
  -d '{"repo": "owner/repo", "callback_url": "https://your-webhook.com/done"}'

# Status
curl http://localhost:8091/api/cycle/{cycle_id}

# List recent
curl http://localhost:8091/api/cycles

# Cancel
curl -X POST http://localhost:8091/api/cycle/{cycle_id}/cancel
```

`callback_url` (optional) — POSTed when the cycle completes.

---

## GitHub webhook

```
POST https://your-domain.com/webhooks/github
```

HMAC-SHA256 verified. Triggers cycles on push to default branch, new issues, PR review requests.

---

## Configuration

### Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | yes (real) | Claude API access |
| `GITHUB_TOKEN` | yes (real) | GitHub API |
| `SWARM_GITHUB_REPO` | yes (legacy mode) | Default target repo |
| `SWARM_PO_GITHUB_REPOS` | no | Comma-separated repo allowlist |
| `SWARM_PO_MATTERMOST_TOKEN` | no | `@swarm-po` Mattermost token |
| `MATTERMOST_BOT_TOKEN` | no | Shared Mattermost token |
| `EXTERNAL_URL` | no | Public URL for button callbacks |
| `BASE_PATH` | no | Reverse-proxy prefix (e.g. `/swarm`) |
| `SEQ_URL` | no | Seq endpoint for logs |
| `SEQ_API_KEY` | no | Seq API key |

### `theswarm.yaml`

```yaml
mattermost:
  base_url: "https://your-mattermost.com"
  channel_name: "swarm-bots-logs"

server:
  host: "0.0.0.0"
  port: 8091
  external_url: "https://your-domain.com"

agents:
  swarm_po:
    enabled: true
    llm_backend: "claude-code"
    github_repos: ["owner/repo-1", "owner/repo-2"]
    default_repo: "owner/repo-1"
    team_channel: "swarm-team"
```

Env vars override YAML.

### Storage

`~/.swarm-data/`:
- `theswarm.db` — SQLite (projects, cycles, schedules, reports, memory, prompt library, audit log).
- `artifacts/{cycle_id}/` — demo screenshots/videos, served at `/artifacts/{path}`.

Per-repo agent memory: `AGENT_MEMORY.jsonl` checked into the target repo.

---

## Deployment

### Docker

```bash
docker compose up
```

### Docker Swarm + Traefik

```bash
docker stack deploy -c docker-compose.yml theswarm
```

Routes through Traefik at `PathPrefix(/swarm)`. Container mounts host's `~/.claude` for Claude CLI subscription auth.

### CI/CD

- `ci.yml` — `uv run pytest tests/ -v --tb=short --ignore=tests/e2e -p no:playwright` on push/PR.
- `cd.yml` — builds image to GHCR, deploys via `docker stack up`.

---

## Architecture

Clean Architecture / DDD. Two packages in `src/`:

- `theswarm` — agents, cycle orchestration, gateway, dashboard.
- `theswarm_common` — shared infrastructure (Mattermost adapter, config loader, models).

```
src/theswarm/
├── domain/               # frozen dataclasses, value objects, Protocol ports
├── application/          # CQRS commands/queries, EventBus, services, DTOs
├── infrastructure/       # SQLite repos, schedulers, webhook, ticket sources, recorders
└── presentation/
    ├── cli/              # argparse CLI
    ├── web/              # FastAPI + HTMX + Jinja2 + SSE
    │   ├── routes/       # 33 route modules (one per role + portfolio surfaces)
    │   ├── templates/    # server-rendered HTML
    │   └── static/       # design-system CSS, SSE client
    └── tui/              # Textual dashboard
```

### Issue label state machine

```
status:backlog → status:ready → status:in-progress → status:review → merged/closed
```

### Bounded contexts

Projects · Cycles · Agents · Tickets · Memory · Reporting · Scheduling · Chat.
Domain entities are frozen dataclasses. Ports are Protocols. Infrastructure implements them.

---

## Testing

```bash
# All unit + integration (~2100 tests)
uv run pytest tests/ -v --tb=short --ignore=tests/e2e -p no:playwright

# Single test
uv run pytest tests/test_cycle.py::test_stub_cycle_runs -v

# By layer
uv run pytest tests/domain/ -v          # 100 % coverage target
uv run pytest tests/application/ -v
uv run pytest tests/infrastructure/ -v
uv run pytest tests/presentation/ -v
uv run pytest tests/integration/ -v

# E2E (separate — Playwright sync fixtures conflict with pytest-asyncio)
uv run pytest tests/e2e/ -v --headed
```

Conventions:
- pytest with `asyncio_mode = "auto"`.
- `respx` for HTTP mocks, `pytest-mock` for general.
- AAA test structure, descriptive names (`test_returns_empty_when_…`).

---

## License

MIT
