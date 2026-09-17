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
  excluded from the CI trigger — then the PO's daily *report*
  (`docs/daily-reports/**`) and the memory save (`AGENT_MEMORY.jsonl`)
  did it again at the end of cycle `5f8f0f63f58c`, two deploys in a
  minute while QA was still finishing. Adding a new agent write-to-main
  path means adding it to that `paths-ignore` too.
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
- **One cycle per repository at a time** — `cycle.repo_lock`, held by the
  API wrapper, the Mattermost gateway and the autonomous loop; a second
  cycle shows `queued`. Two cycles on one repo share one workspace and erase
  each other's branches (`16f3b8af2cca` vs `2878898cc504`: two commits, no PR).
- **Cancel is persisted** (`CycleCancelled` → cycles table). The resumer
  reads `list_running()` at boot; before #96 a cancelled cycle came back
  after every deploy, on top of whatever had replaced it.
- **On `SELF_REPO` the TechLead approves but never merges** — a merge to
  main redeploys this service and kills the cycle mid-review. Approved PRs
  come back as `held_prs`; a person merges them between cycles.
- **Phases are announced**, not guessed: `cycle.py` sends
  `on_progress(PHASE_ROLE, name)` through `_announce`, the bridge turns it
  into the real `PhaseChanged` and the theater's graph reads that history.
  A new phase or sub-phase needs an `_announce` call and a `PHASE_OWNER`
  entry, or the graph will not know who owns it.
- `ClaudeCLI` **remembers the largest budget that already expired** and
  never offers it again within a cycle (`_timeout_floor`, ceiling 780s —
  `dev_iter` is 30 min so one call plus its retry fit). The task picker
  puts an already-tried sub-task behind the untried ones; without that the
  heaviest task starved the rest for five iterations.
- CI reports a `tests` job that hits `timeout-minutes` as **"cancelled"** —
  it is neither a failure nor a person hitting stop. The cap is 30 min; the
  suite runs 9–12 on a healthy shared runner.
- **The quality gate reads the target's toolchain.** `requirements.txt` when
  present; otherwise `pyproject.toml` installed editable with its PEP 735
  `dev` group (what `uv sync --dev` reads) — TheSwarm itself is that case,
  and installed nothing until #103, so `pytest` was missing and no PR ever
  came out of a self-cycle. A runner that reports its own absence, and a
  suite that outruns `TEST_RUN_TIMEOUT_SECONDS` (120s; TheSwarm's takes 3
  min locally), are `tests_unavailable`: no Ralph rounds, the PR opens
  with the reason in its body, and the repository's CI is the judge.
  Installing TheSwarm into the container's system python takes ~63s cold.
- **The Dev's working tree is the truth, not Claude's last message.**
  `claude -p` grants nothing: an `Edit` in the workspace is refused, Claude
  writes the files into an intermediate message and ends with a summary,
  and `--output-format json` carries only that summary — a five-minute
  implementation of #114 became "no file changes" (#125). Implementation
  and Ralph-retry calls run with `--permission-mode acceptEdits`; the
  `--- FILE:` blocks are the fallback for the *final* message; both paths
  end in `commit_all`, whose answer decides. The container's Bash
  allowlist is the host's `~/.claude/settings.json` mounted in — do not
  rely on it.
- **A PR is reviewed once per cycle, at a given head** (`reviewed_prs`,
  the cycle's own list, threaded into every `techlead_review` pass). The
  review node runs after every Dev iteration; a held (SELF_REPO) or
  commented PR is still open next time and nothing about it changed —
  cycle 5f8f0f63f58c read #124 three times and the 300s phase timed out
  on the pass that mattered. A new push changes the key and earns a new
  review.
- **The verdict is read wherever the reviewer put it.** Prose, then a
  fenced ```json block, is a common shape; the parser takes the first
  object that carries a `decision`, fenced or bare, and steps over braces
  in prose (`{id}`) and example payloads. Slicing first-`{`-to-last-`}`
  filed an APPROVE with three issues as COMMENT (#126).
- **A failed attempt leaves a trace on the issue** (`ATTEMPT_MARKER` comment,
  `agents/dev._note_failed_attempt`), and the picker reads those back: a
  sub-task that failed in an earlier cycle goes behind its untried siblings
  from the first iteration. The learned CLI timeout floor is also kept per
  workspace across cycles (`tools/claude._REPO_FLOORS`). Before both, every
  self-cycle spent its first sixteen minutes re-timing-out on #89 (#99).
- **The Dev is told about its siblings' open PRs** (`_sibling_prs`: title +
  files, in the prompt above the `ALREADY_SATISFIED` rule). Four sub-tasks
  of one story built in parallel each re-implemented the others' work
  (#104/#105/#108/#109). Their branches are still not in the checkout — the
  human who merges must still pick the complete one and close the rest.
- **QA starts a target the way it declares** — `demo.command` / `demo.env`
  in the target's `theswarm.yaml` (`agents/qa._demo_launch`), in a scrubbed
  environment: only `PATH`/`HOME`/… plus `demo.env` reach the process, never
  this instance's tokens. Without a declaration: `uvicorn src.main:app` with
  the environment it always had. TheSwarm declares `python -m theswarm serve
  --port {port} --db {tmp}/demo.db` with `SWARM_AUTH_DISABLED=1` (#110).
- **The GitHub circuit breaker ignores 4xx** (`tools/github._is_client_error`):
  a 422 "cannot review your own pull request" is a fact about the request,
  not an outage. Four of them opened the breaker and blocked the memory save
  at the end of the first self-cycle (#111); the save now also waits out an
  open circuit once (`memory_store.CIRCUIT_RETRY_DELAY_SECONDS`).
- **QA's budgets on the swarm's own repo.** The first self-cycle to reach QA
  with the demo declaration (`5f8f0f63f58c`) produced a blank demo card and a
  report of `unit=0(pass) e2e=141(fail)`: the unit-test run hit a hardcoded
  120s cap and `_parse_pytest_summary` read the empty output as a vacuous
  0/0 pass (`unit_tests_not_run_reason` now marks a timed-out run `not_run`
  instead, on its own `QA_TEST_TIMEOUT_SECONDS` budget, 600s); the readiness
  wait was a flat 30s against `theswarm serve`'s ~30s container boot, so
  every screenshot attempt logged `ERR_CONNECTION_REFUSED` three times over
  (`demo.ready_seconds` in `theswarm.yaml`, TheSwarm declares 90, and
  `capture_demo_screenshots` returns no artifacts on one readiness failure
  instead of trying anyway); and the E2E run picked up the target's own 132
  Playwright tests instead of the file QA wrote (`run_e2e_tests` now scopes
  to `tests/e2e/test_api_e2e.py` alone). The thumbnail was frame 0 — a blank
  page mid-boot — because `make_thumbnail` seeked to a fixed 1s in; it now
  seeks to the midpoint of the video's duration, or the last frame when the
  duration can't be read (#132).
