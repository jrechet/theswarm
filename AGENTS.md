# AGENTS.md

TheSwarm is an autonomous AI dev team: four agents (PO, TechLead, Dev, QA) built as
LangGraph state graphs run a full development cycle — plan, implement, review, test,
report — against a registered GitHub repo. A FastAPI + HTMX dashboard, a CLI, and a
Mattermost persona drive it.

## Build & test

```bash
uv sync --dev                                                  # install (uv, not pip)
uv run pytest tests/ -v --tb=short --ignore=tests/e2e -p no:playwright   # unit/integration
uv run pytest tests/e2e/ -v                                    # E2E (needs running server)
uv run python -m theswarm                                      # unified server on :8091
uv run python -m theswarm cycle --project concert-tour-app     # run one cycle
uv run python -m theswarm validate                             # check env vars
```

E2E tests must run separately: pytest-playwright's sync fixtures conflict with
pytest-asyncio. CI runs `--ignore=tests/e2e -p no:playwright`.

## Architecture

Two packages in `src/`: `theswarm` (agents, cycle, web) and `theswarm_common`
(Mattermost adapter, config loader). Clean Architecture layout:

- `domain/` — frozen dataclasses, value objects, Protocol ports
- `application/` — CQRS commands/queries, EventBus, services
- `infrastructure/` — SQLite (aiosqlite) repos, Playwright recorder, scheduler, webhooks
- `presentation/` — CLI (argparse), web (FastAPI + HTMX + SSE), TUI (Textual)

Original pipeline modules, bridged into the web app: `cycle.py` (orchestration,
`PHASE_TIMEOUTS`), `agents/{po,techlead,dev,qa}.py`, `tools/{claude,github,git}.py`,
`api.py` (cycle tracker + whole-cycle hard timeout), `persona.py` (Mattermost NLU).
Full details: `docs/ARCHITECTURE-V2.md`, `docs/ROLES-OVERVIEW.md`.

## Conventions

- Issues flow `status:backlog → ready → in-progress → review → merged/closed`;
  the Dev agent picks `role:dev` + `status:ready`.
- Stub mode: without `SWARM_GITHUB_REPO`/registered project, agents log intents and
  make no API calls. Tests rely on it.
- pytest `asyncio_mode = "auto"`; `respx` for HTTP mocking; tests organized by layer
  under `tests/{domain,application,infrastructure,presentation,integration,e2e}`.
- 2200+ tests, all green. Any key an agent node returns MUST be declared in
  `AgentState` (`config.py`) — LangGraph silently drops undeclared keys
  (guarded by `tests/test_agent_state_schema.py`).

## Environment

Secrets in `.env` (never committed). Key vars: `ANTHROPIC_API_KEY` (only a real
`sk-ant-api` key enables the API fallback; an `sk-ant-oat` OAuth token is
CLI-only and is deliberately ignored by the fallback), `GITHUB_TOKEN` (push auth,
injected per git command — never written to `.git/config`), `SWARM_GITHUB_REPO`,
`MATTERMOST_BOT_TOKEN`, `BASE_PATH` (reverse-proxy prefix, templates use
`{{ base }}`), `SEQ_URL`/`SEQ_API_KEY` (log aggregation).

## Deployment

CI (GitHub Actions) → GHCR image → Docker Swarm + Traefik on the self-hosted box.
PR CI is the quality gate; a push to main deploys immediately (tests re-run in
parallel as a safety net, and the deploy job rolls back if the service does not
come up healthy). Never push to main without a green PR.
Prod: <https://bots.jrec.fr/swarm> — logs: <https://logs.jrec.fr> (Seq).
Done means: merged on `main`, deploy landed, behavior re-verified on prod
(trigger a real cycle and read the phase timeline).

## Operational landmines (learned in production)

- One aiosqlite connection is shared by every repo; aiosqlite serializes per
  connection. Never put an unbounded DB call in a liveness path — `/health`
  bounds its probe at 1s for exactly this reason (a busy cycle used to get the
  container killed by the Docker healthcheck).
- Claude backend is CLI-first (subscription billing); the API is a fallback only
  when a usable API key exists. Model names are aliases (`sonnet` →
  `claude-sonnet-5`) — never pin dated model IDs.
- The target workspace uses the *system* python (`agents/base.find_system_python`)
  for installs AND test runs — TheSwarm's venv must never receive target deps.
- Phase budgets: implementation call 420s, dep install 300s, `dev_iter` 25 min.
  If a task fails, it must be requeued to `status:ready` (see `implement_task`) or
  the backlog drains with nothing shipped.
- `commit_all` uses `git add -A` in the target workspace: runtime artifacts
  (test.db*, coverage) must be excluded before commit — known gap.
