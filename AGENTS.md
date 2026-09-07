# AGENTS.md

TheSwarm is an autonomous AI dev team: four agents (PO, TechLead, Dev, QA) built as
LangGraph state graphs run a full development cycle — plan, implement, review, test,
report — against a registered GitHub repo. A FastAPI dashboard, a CLI, and a
Mattermost persona drive it. The front door is the V2 flow (sign in → pick a
repo → write a feature → ▶ Play → watch the four agents in the theater); the
older V1 surfaces stay reachable under "Legacy".

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
- `presentation/` — CLI (argparse), web (FastAPI + Jinja + SSE), TUI (Textual)

Two UI generations coexist in `presentation/web/`:
- **V2** — `routes/v2.py` + `templates/v2/` on Tailwind tokens (`static/v2/input.css`,
  Plex fonts vendored, no CDN). Owns `/` (repo picker fed by the GitHub App
  installation plus legacy registered projects), `/r/{owner}/{name}` (composer →
  GitHub issue, issue board, ▶ Play), `/c/{cycle_id}` (the theater: agent rail from
  `ProgressBridge` live messages, pinned issue breakdown via
  `application/services/pinned_issue.py`, feed from the cycle event store; the
  page polls `/c/{id}/stage` every 3 s and only swaps the DOM on change).
- **V1** — everything else (`/dashboard`, `/projects/`, `/cycles/`, HTMX
  fragments, the 14 role surfaces). Demoted, not deleted; the theater sends
  cycles the in-memory tracker no longer knows to `/cycles/{id}` (archive view).

`presentation/web/auth.py` is the wall (pure ASGI, fail-safe closed); doors are
`routes/auth_routes.py` (access key + GitHub OAuth) and the GitHub App setup in
`routes/github_setup.py`.

Original pipeline modules, bridged into the web app: `cycle.py` (orchestration,
`PHASE_TIMEOUTS`), `agents/{po,techlead,dev,qa}.py`, `tools/{claude,github,git,github_app}.py`,
`api.py` (cycle tracker + whole-cycle hard timeout), `persona.py` (Mattermost NLU).
Full details: `docs/ARCHITECTURE-V2.md`, `docs/ROLES-OVERVIEW.md`.

## Conventions

- Issues flow `status:backlog → ready → in-progress → review → merged/closed`;
  the Dev agent picks `role:dev` + `status:ready`.
- Stub mode: without `SWARM_GITHUB_REPO`/registered project, agents log intents and
  make no API calls. Tests rely on it.
- pytest `asyncio_mode = "auto"`; `respx` for HTTP mocking; tests organized by layer
  under `tests/{domain,application,infrastructure,presentation,integration,e2e}`.
- 2300+ tests, all green. Any key an agent node returns MUST be declared in
  `AgentState` (`config.py`) — LangGraph silently drops undeclared keys
  (guarded by `tests/test_agent_state_schema.py`).
- GitHub identity: `tools/github_app.ensure_github_token()` exports the freshest
  token (1 h installation token when the App is configured, else the static
  `GITHUB_TOKEN`) as `GITHUB_TOKEN`; every `GitHubClient` method calls `_fresh()`
  first so a 3 h cycle survives token rotation. Without App credentials the
  static token passes straight through — that is the rollback path.
- Play → cycle is the `issue_number` → `CycleConfig.target_issue` mechanic: the
  Dev agent takes the pinned issue if it carries `role:dev`, else its
  `Parent: #N` children in `status:ready`.

## Environment

Secrets in `.env` (never committed). Key vars: `CLAUDE_CODE_OAUTH_TOKEN`
(headless auth for the Claude CLI, minted with `claude setup-token`; the
browser-session credentials mounted from the host expire when their refresh
token dies), `ANTHROPIC_API_KEY` (only a real `sk-ant-api` key enables the API
fallback; an `sk-ant-oat` OAuth token is CLI-only and is deliberately ignored
by the fallback), `GITHUB_TOKEN` (push auth,
injected per git command — never written to `.git/config`), `SWARM_GITHUB_REPO`,
`MATTERMOST_BOT_TOKEN`, `BASE_PATH` (reverse-proxy prefix, templates use
`{{ base }}`), `SEQ_URL`/`SEQ_API_KEY` (log aggregation), `SWARM_ACCESS_KEY`/`SWARM_SESSION_SECRET`
(dashboard auth wall — fail-safe closed; `SWARM_AUTH_DISABLED=1` opens it for
local dev/tests only; the access key also works as `Authorization: Bearer` on
`/api/*`), `SWARM_OWNER_LOGIN` (the only GitHub login OAuth admits; default
`jrechet`). GitHub App credentials live in the Fernet vault under project id
`__github_app__` (written by the manifest callback); `GITHUB_APP_ID` +
`GITHUB_APP_PRIVATE_KEY` (+ `_CLIENT_ID`/`_CLIENT_SECRET`) are the env fallback
for CLI/dev contexts without a vault. Prod env flows repo secrets →
`.github/actions/write-env` → `.env` → `env_file` — a new variable needs all three.

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
- The cycle tracker is in-memory: a container restart forgets running cycles
  (issue #5), and the theater can only show cycles it still knows.
- The GitHub App manifest flow is broken (GitHub returns a code it does not
  recognise, no app is created) and **is not needed**: repos come from
  `github_app.list_user_repositories()` with the owner's `GITHUB_TOKEN`, and
  "Sign in with GitHub" runs on a plain OAuth App
  (`/setup/github-oauth`, vault `__github_oauth__`). Do not sink time into
  the manifest flow; the investigation is in
  `docs/handoffs/2026-09-06-github-app-manifest-conversion-404.md`.
- **Anything that commits to `main` of a repo a cycle is running against
  redeploys the service and kills that cycle** — the tracker is in-memory
  (#5). The PO's daily plan did exactly that until `docs/daily-plans/**` was
  excluded from the CI trigger. Adding a new agent write-to-main path means
  adding it to that `paths-ignore` too.
- Waiting for a deploy: check the **running container's** image
  (`docker inspect $(docker ps -q -f name=theswarm_theswarm)`), not the
  service spec — the spec updates when the rollout *starts*, and `/health`
  is answered by the old container throughout. Acting on the spec means
  talking to a container that is about to die.
- Claude CLI failure modes are three, and they need different handling:
  a **timeout** must be retried with more room (`_retry_timeout`), an
  **auth** failure retries once without `CLAUDE_CODE_OAUTH_TOKEN`
  (`_cli_with_auth_recovery`, on *every* attempt), and an exhausted
  **subscription window** is fatal — retrying it burns the remaining
  iterations in seconds against a wall and reports a credential error that
  sends the reader hunting for a bug that does not exist.
- `GitHubClient._fresh()` rebinds only when App credentials exist. A static
  `GITHUB_TOKEN` never rotates, and rebuilding on a mere difference replaces
  clients built deliberately with a mock — that is how a token in the
  environment made 13 tests call the live API.
- Tests must not assert git argv **by position**: `_auth_args()` prepends
  credential flags whenever `GITHUB_TOKEN` is set, so index-based assertions
  silently depend on the suite's environment.
- `static/v2/app.css` is generated: never commit it. It slipped in twice —
  the `.gitignore` pattern had no leading `**/`, so a mid-path `/` anchored it
  to the repo root and `git add -A` kept re-adding the file.
