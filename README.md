# TheSwarm

Autonomous AI dev team. Four specialized agents (PO, TechLead, Dev, QA) that receive feature requests via Mattermost DMs and execute the full development cycle: planning, implementation, code review, testing, and reporting.

You describe what you want. TheSwarm builds it, reviews it, tests it, and reports back.

## How It Works

```
You (Mattermost DM)          TheSwarm Agents              Your Repo
       |                          |                          |
  "Add dark mode"                 |                          |
       |-----> PO: generates      |                          |
       |       user stories       |                          |
       |<----- "Approve?"         |                          |
       |                          |                          |
  "Approve"                       |                          |
       |-----> PO: creates        |                          |
       |       GitHub issues  ----|------------------------->|
       |                          |                          |
  "go"                            |                          |
       |-----> PO: daily plan     |                          |
       |       TechLead: breaks   |                          |
       |         stories into     |                          |
       |         dev tasks        |                          |
       |       Dev: implements    |                          |
       |         (up to 5 PRs) ---|-------- opens PRs ------>|
       |       TechLead: reviews  |                          |
       |         and merges    ---|-------- merges PRs ----->|
       |       QA: runs tests,    |                          |
       |         security scan,   |                          |
       |         generates demo   |                          |
       |       PO: validates,     |                          |
       |         writes report    |                          |
       |<----- "Cycle complete!   |                          |
       |        3 PRs merged,     |                          |
       |        $0.42 spent"      |                          |
```

## Quickstart

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- An Anthropic API key (`ANTHROPIC_API_KEY`)
- A GitHub personal access token (`GITHUB_TOKEN`)

### 1. Install

```bash
git clone https://github.com/jrechet/theswarm.git
cd theswarm
uv sync --dev
```

### 2. Configure environment

Create a `.env` file (or export env vars):

```bash
# Required for real mode
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...

# Target repo (the repo TheSwarm will work on)
SWARM_GITHUB_REPO=owner/my-app

# Optional: Mattermost chat integration
SWARM_PO_MATTERMOST_TOKEN=your-bot-token
MATTERMOST_BOT_TOKEN=your-bot-token
EXTERNAL_URL=https://your-domain.com
```

### 3. Validate configuration

```bash
uv run python -m theswarm validate
```

This checks all required env vars and reports errors/warnings before you start.

### 4. Start the server

```bash
uv run python -m theswarm
```

This starts the unified server on port 8091 with:
- Web dashboard at `http://localhost:8091`
- Real-time SSE updates at `http://localhost:8091/swarm/dashboard`
- Health check at `http://localhost:8091/health`
- Headless API at `http://localhost:8091/api/cycle`
- Mattermost webhook handler (if configured)

### 5. Run a cycle

**Via Mattermost DM** (if configured): message `@swarm-po` with `go`

**Via CLI:**
```bash
uv run python -m theswarm --cycle
```

**Via API:**
```bash
curl -X POST http://localhost:8091/api/cycle \
  -H "Content-Type: application/json" \
  -d '{"repo": "owner/my-app"}'
```

## Stub Mode

When `SWARM_GITHUB_REPO` is not set, agents run in stub mode. They log what they would do but make no API calls. Good for testing the pipeline without spending money.

```bash
# No env vars needed
uv run python -m theswarm --cycle
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `python -m theswarm` | Start the unified server (default) |
| `python -m theswarm serve` | Same as above (explicit) |
| `python -m theswarm serve --port 9000` | Custom port |
| `python -m theswarm validate` | Check env vars before starting |
| `python -m theswarm status` | Show registered projects and active cycles |
| `python -m theswarm dashboard` | Terminal UI dashboard |
| `python -m theswarm --cycle` | Run a full daily cycle from CLI |
| `python -m theswarm --dev-only` | Run only the Dev agent |
| `python -m theswarm --techlead-only` | Run only the TechLead agent |

### Project Management

```bash
# Register a repo as a project
python -m theswarm projects add my-app owner/my-app
python -m theswarm projects add my-app owner/my-app --framework fastapi

# List registered projects
python -m theswarm projects list

# Remove a project
python -m theswarm projects remove my-app

# Run a cycle for a registered project
python -m theswarm cycle --project my-app
```

### Scheduling

```bash
# Set a cron schedule (weekdays at 8am)
python -m theswarm schedule set my-app "0 8 * * 1-5"

# List active schedules
python -m theswarm schedule list

# Disable without deleting
python -m theswarm schedule disable my-app

# Delete a schedule
python -m theswarm schedule delete my-app
```

## The Agents

### PO (Product Owner)
- Receives feature descriptions via Mattermost DM
- Generates user stories with acceptance criteria using Claude
- Creates GitHub issues with `status:backlog` labels
- Writes daily plans (morning) and validates demo reports (evening)

### TechLead
- Breaks user stories into implementable dev tasks
- Reviews all PRs via Claude (code quality, architecture, tests)
- Approves and merges PRs that pass review
- Requests changes on PRs that need work

### Dev
- Picks `status:ready` tasks from the backlog
- Implements features using Claude (Anthropic API)
- Runs tests locally before opening PRs
- Iterates up to 5 times per cycle

### QA
- Writes and runs Playwright E2E tests
- Runs unit test suite
- Runs semgrep security scan
- Generates demo report with screenshots, coverage, and quality gates

## Chat Interface (Mattermost)

DM `@swarm-po` with any of these:

| Message | What happens |
|---------|-------------|
| `Add Google auth` / any feature description | Generates user stories for approval |
| `go` / `start` / `lance` | Launches a dev cycle on the default repo |
| `go on owner/repo` | Launches a cycle on a specific repo |
| `status` | Checks if a cycle is running |
| `plan` / `plan du jour` | Shows today's daily plan |
| `rapport` / `report` | Shows the latest daily report |
| `backlog` / `issues` | Lists open GitHub issues |
| `repos` | Lists allowed repositories |
| `ping` | Tests button callbacks (interactive buttons) |
| `help` | Shows the help message |

Channel commands (in any channel): `!swarm-po status`, `!swarm-po plan`, `!swarm-po report`

## Web Dashboard

The web dashboard at `http://localhost:8091` shows:
- Registered projects and their status
- Cycle history with cost tracking
- Real-time SSE updates during active cycles
- Demo reports with quality gates

The legacy real-time dashboard at `/swarm/dashboard` shows live cycle events via SSE.

## Headless API

```bash
# Start a cycle
curl -X POST http://localhost:8091/api/cycle \
  -H "Content-Type: application/json" \
  -d '{"repo": "owner/repo", "callback_url": "https://your-webhook.com/done"}'

# Check cycle status
curl http://localhost:8091/api/cycle/{cycle_id}

# List recent cycles
curl http://localhost:8091/api/cycles

# Cancel a running cycle
curl -X POST http://localhost:8091/api/cycle/{cycle_id}/cancel
```

When `callback_url` is provided, TheSwarm POSTs the result when the cycle completes.

## GitHub Webhooks

TheSwarm can auto-trigger cycles on push events. Configure a GitHub webhook pointing to:

```
POST https://your-domain.com/webhooks/github
```

Set the webhook secret in your config. TheSwarm verifies the HMAC-SHA256 signature.

Triggers on:
- Push to the default branch
- New issues opened
- PR review requests

## Configuration

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes (real mode) | Claude API access for all agents |
| `GITHUB_TOKEN` | Yes (real mode) | GitHub API operations (issues, PRs, reviews) |
| `SWARM_GITHUB_REPO` | Yes (real mode) | Default target repo (`owner/repo`) |
| `SWARM_PO_GITHUB_REPOS` | No | Comma-separated allowlist of repos |
| `SWARM_PO_MATTERMOST_TOKEN` | No | Mattermost bot token for @swarm-po |
| `MATTERMOST_BOT_TOKEN` | No | Shared Mattermost bot token |
| `EXTERNAL_URL` | No | Public URL for Mattermost button callbacks |
| `SEQ_URL` | No | Seq log aggregation endpoint |
| `SEQ_API_KEY` | No | Seq API key |

### theswarm.yaml

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
    github_repos:
      - "owner/repo-1"
      - "owner/repo-2"
    default_repo: "owner/repo-1"
    team_channel: "swarm-team"
    channel: "swarm-bots-logs"
```

Env vars override YAML values. The `external_url` automatically gets `/swarm` appended for Traefik routing.

### Data Storage

TheSwarm stores data in `~/.swarm-data/`:
- `theswarm.db` — SQLite database (projects, cycles, schedules, reports)
- `artifacts/` — cycle artifacts (screenshots, videos, diffs)

Agent memory (learnings, retrospectives) is stored as `AGENT_MEMORY.jsonl` in the target repo itself.

## Deployment

### Docker

```bash
docker compose up
```

The `docker-compose.yml` configures:
- Port 8091 exposed
- `.env` file for secrets
- Health check via `/health`
- 1GB memory limit
- Traefik labels for reverse proxy routing

### Docker Swarm + Traefik

```bash
docker stack deploy -c docker-compose.yml theswarm
```

Routes through Traefik at `PathPrefix(/swarm)` on your domain. The container mounts the host's `.claude` config directory for Claude Code access.

### CI/CD

The GitHub Actions pipeline:
1. **CI** (`ci.yml`): runs `uv run pytest tests/ -v --tb=short` on push/PR
2. **CD** (`cd.yml`): builds container image to GHCR, deploys via `docker stack up`

## Architecture

```
python -m theswarm
  |
  v
__main__.py  -->  presentation/cli/main.py  -->  presentation/web/server.py
                                                    |
                                                    |-- v2 web app (FastAPI + HTMX + Jinja2)
                                                    |     |-- /           (dashboard)
                                                    |     |-- /projects   (CRUD)
                                                    |     |-- /cycles     (run + status)
                                                    |     |-- /reports    (view + approve)
                                                    |     |-- /health     (real connectivity check)
                                                    |     |-- /webhooks   (GitHub HMAC)
                                                    |
                                                    |-- Legacy routes (backward compat)
                                                    |     |-- /swarm/dashboard  (SSE live view)
                                                    |     |-- /swarm/reports    (HTML reports)
                                                    |     |-- /api/cycle        (headless API)
                                                    |
                                                    |-- GatewayBridge
                                                    |     |-- Mattermost WS listener
                                                    |     |-- persona.py (NLU DM handler)
                                                    |     |-- wiring.py (button callbacks)
                                                    |
                                                    |-- Agents (LangGraph)
                                                          |-- PO (morning + evening)
                                                          |-- TechLead (breakdown + review)
                                                          |-- Dev (implement, up to 5 iters)
                                                          |-- QA (test + security + demo)
```

The system follows Clean Architecture / DDD with 8 bounded contexts: Projects, Cycles, Agents, Tickets, Memory, Reporting, Scheduling, Chat. Domain entities are frozen dataclasses. Ports are Protocols. Infrastructure implements the ports.

### Issue Label State Machine

Issues flow through GitHub labels:

`status:backlog` -> `status:ready` -> `status:in-progress` -> `status:review` -> merged/closed

## Testing

```bash
# Run all tests (890+)
uv run pytest tests/ -v --tb=short

# Run a single test
uv run pytest tests/test_cycle.py::test_stub_cycle_runs -v

# Run by layer
uv run pytest tests/domain/ -v          # domain entities (100% coverage target)
uv run pytest tests/application/ -v     # commands, queries, services
uv run pytest tests/infrastructure/ -v  # SQLite, schedulers, webhooks
uv run pytest tests/presentation/ -v    # CLI, web app, TUI
uv run pytest tests/integration/ -v     # cross-layer end-to-end
```

Test organization:
- `tests/domain/` — domain entities, value objects (100% coverage target)
- `tests/application/` — command handlers, queries, event bus, services
- `tests/infrastructure/` — SQLite repos, artifact store, cron scheduler, webhooks
- `tests/presentation/` — CLI parsing, web app (httpx ASGI), TUI (Textual pilot), unified server
- `tests/integration/` — full-stack flows (project -> cycle -> dashboard), unified server route coexistence
- `tests/test_*.py` — original agent and tool tests

## License

MIT
