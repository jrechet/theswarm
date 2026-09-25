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
- The Claude backend is the Agent SDK, on the subscription; the API is a
  fallback only when a usable API key exists. The `claude -p` CLI backend
  was retired on 2026-09-25 (V2 M7) — `SWARM_CLAUDE_BACKEND=cli` now runs
  on the SDK with a warning. Model names are aliases (`sonnet` →
  `claude-sonnet-5`) — never pin dated model IDs.
- The target workspace uses its own `.venv-swarm` (`agents/base.find_system_python`)
  for installs AND test runs — TheSwarm's venv must never receive target deps.
  **That includes Claude's own Bash.** The container's PATH starts with
  TheSwarm's venv; on 2026-09-23 a Dev that wanted to try the tests ran
  `uv pip install -r requirements.txt --python /app/.venv/bin/python`
  (cycle 83b584194589) and replaced TheSwarm's fastapi, pydantic and uvicorn
  with the target's pins under the running server. Every Claude child with
  a workspace now gets that workspace's venv first on PATH and in
  VIRTUAL_ENV, TheSwarm's venv off PATH (`tools/claude._python_for_target`),
  the Dev builds the venv before its first call, and the policy hook refuses
  any Bash command that names TheSwarm's own `sys.prefix`.
- Phase budgets (`cycle_budgets.PHASE_TIMEOUTS`): implementation call 600s,
  dep install 300s, `dev_iter` 40 min, `techlead_review` 30 min.
  If a task fails, it must be requeued to `status:ready` (see `implement_task`) or
  the backlog drains with nothing shipped.
- `commit_all` uses `git add -A` in the target workspace: runtime artifacts
  (test.db*, coverage, `.venv-swarm/`, `.worktrees/`) never reach a commit —
  closed in V2 M5a by the clone's `.git/info/exclude` (`tools/git.exclude_locally`).
- The cycle tracker is in-memory, but a restart no longer loses a running
  cycle (V2 runtime M4, closes the practical side of #5): the boot resumer
  continues it under a new tracker id, `/c/{old}` redirects to it while it
  runs, and the archive view shows it afterwards.
- The GitHub App manifest flow is broken (GitHub returns a code it does not
  recognise, no app is created) and **is not needed**: repos come from
  `github_app.list_user_repositories()` with the owner's `GITHUB_TOKEN`, and
  "Sign in with GitHub" runs on a plain OAuth App
  (`/setup/github-oauth`, vault `__github_oauth__`). Do not sink time into
  the manifest flow; the investigation is in
  `docs/handoffs/2026-09-06-github-app-manifest-conversion-404.md`.
- **Anything that commits to `main` of this repo redeploys the service and
  interrupts a running cycle** — it no longer kills it (V2 runtime M4).
  Proven on prod 2026-09-23: a forced restart during the Dev phase of
  `747bb89eced2`; the new container resumed it as `83b584194589` within a
  second of booting, and it finished with three PRs reviewed and merged
  (harness PASS, $2.81). What an interruption still costs: the stop-first
  gap (a minute or two of 404s) and the node in flight — the interrupted
  Dev iteration starts over with its claimed tasks handed back; the tree
  survives on the `swarm-workspaces` volume. A continuation is never
  resumed a second time (`auto-resume:1`), so two deploys inside one
  cycle still lose it. The resume also needs the old container not to
  write the cycle down as cancelled on its way out (see "Cancel is
  persisted"). Keep agent write-to-main paths out of the CI
  trigger anyway: the PO's daily plan, its daily *report*
  (`docs/daily-reports/**`) and the memory save (`AGENT_MEMORY.jsonl`) each
  redeployed mid-cycle once (`5f8f0f63f58c`: two deploys in a minute while
  QA was still finishing). A new agent write-to-main path goes into
  `paths-ignore` too.
- Waiting for a deploy: check the **running container's** image
  (`docker inspect $(docker ps -q -f name=theswarm_theswarm)`), not the
  service spec — the spec updates when the rollout *starts*, and `/health`
  is answered by the old container throughout. Acting on the spec means
  talking to a container that is about to die.
- Claude failure modes are three, and they need different handling
  (`tools/claude._sdk_with_recovery`; the CLI had the same three until M7):
  a **timeout** is resumed with more room (`_retry_timeout`, the same
  session), an **auth** failure retries once without
  `CLAUDE_CODE_OAUTH_TOKEN`, and an exhausted
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
  after every deploy, on top of whatever had replaced it. **Only a cancel a
  person asked for** (`CycleTracker.cancel`, the cancel route) is written
  down: a deploy's SIGTERM cancels every task left at loop teardown, and
  recording that as a cancel lost cycle 04fc7fff85a0 to the deploy of #192
  — the resume was a race between the teardown and the SIGKILL. A
  cancellation nobody asked for propagates and leaves the row `running`.
- **A failed cycle's reason is on its row** (`cycles.error`, v030): the
  exception from `CycleFailed`, or the boot reap's `RESTART_REASON`, plus
  why the resumer left it (`cycle_resumer.record_not_resumed`: already an
  automatic resume, nothing finished, no graph thread, the per-boot cap).
  The tracker kept the text in memory only, and 46ff31375dce, killed by a
  second deploy on 2026-09-25, read "failed" in the API and the harness
  with the reason in one log line.
- **A deploy waits for the running cycle** (`cd.yml`, "Wait for running
  cycles", up to 30 min, then deploys anyway). A merge made while prod was
  idle used to land four to ten minutes later in the middle of the next
  cycle (092596248fb9, 2f5114ae7713 on 2026-09-25); the resume saves the
  finished phases, not the node in flight, and one resume per cycle means
  a second deploy ends it.
- **On `SELF_REPO` the TechLead approves but does not merge in the review
  phase** — a merge to main redeploys this service mid-cycle. Approved PRs
  come back as `held_prs` and the `merge_held` node merges them at the end
  of the cycle, after QA and the report (#173; see below).
- **Phases are announced**, not guessed: the cycle graph's nodes send
  `on_progress(PHASE_ROLE, name)` through `CycleRuntime.announce`/`enter`
  (`cycle_graph.py`), the bridge turns it into the real `PhaseChanged` and
  the theater's graph reads that history. A new phase or sub-phase needs an
  announce call and an entry in `CYCLE_NODE_ROLES`
  (`domain/cycles/value_objects.py`, which `PHASE_OWNER` is built from),
  or the graph will not know who owns it (`test_cycle_announces_phases.py`).
- `ClaudeCLI` **remembers the largest budget that already expired** and
  never offers it again within a cycle (`_timeout_floor`, ceiling 780s —
  `dev_iter` is 30 min so one call plus its retry fit). The task picker
  puts an already-tried sub-task behind the untried ones; without that the
  heaviest task starved the rest for five iterations. **The floor is
  persisted** (`cli_timeout_floors`, primed at boot by
  `tools/claude.prime_repo_floors`): a process lives one cycle here, and
  before #133 every self-cycle paid seven minutes and a dead call to
  relearn the same number. A floor older than 30 days is ignored.
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
  end in `commit_all`, whose answer decides. On the SDK the same holds:
  the Dev runs the `edit` profile (`acceptEdits`), and what Bash may run is
  the PreToolUse policy hook's decision (`decide_tool_use`), never the
  host's `~/.claude/settings.json` (`setting_sources=[]`).
- **The tree is committed before any `ALREADY_SATISFIED` is believed.** A
  timed-out attempt leaves its in-place edits in the workspace; the retry
  reads them, truthfully answers "already satisfied", and before this the
  issue was closed with nothing committed (#133 on `5b1da00155c2`).
  `commit_all` runs first; the claim only counts on a clean tree.
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
- **An approved PR merges only on green CI** (`agents/ci_gate.py`). The
  TechLead merged every APPROVE unread, and no protection stops it:
  concert-tour-app's main requires no check, TheSwarm's exempts the admin
  token the swarm merges with. Red goes back to the Dev (`CI_RED_MARKER`
  beside `CHANGES_MARKER`, the failing checks named); still running is
  waited for, one `CI_WAIT_SECONDS` (300s) per merge pass, then left open;
  unreadable CI merges as before. The swarm's own `theswarm/review` status
  is not CI. The end-of-cycle merge on SELF_REPO reads the same gate.
- **A REQUEST_CHANGES review closes the loop**: the review is copied onto
  the *issue* behind `CHANGES_MARKER`, the label flips back to
  `status:ready`, and the next attempt resumes the branch the review is
  about (`git.resume_branch`, not `create_branch`, which would reset from
  main and discard the commits) and pushes onto the PR that already
  exists. Two rounds on one task is a conversation; at
  `CHANGES_REQUESTED_CAP` it stays in review with a comment for a person.
  Before #121 the review was written on the PR and forgotten, and
  `pick_task` skips `status:review` — so nothing ever came back.
- **A Claude call that fails is a step skipped, not a cycle lost.** Two
  cycles in a row died on an optional call that failed twice — the review
  of a 500-line diff (`bbab1b4ad6e9`) and QA's E2E-file generation
  (`794a644f6889`): the wrapper's `RuntimeError` left the sub-phase and took
  QA, the report and the memory save with it (#147). The review loop skips
  the PR (`skipped_prs`, not marked reviewed, so it is read next pass) and
  QA goes on without an E2E file; only `ClaudeFatalError` (subscription
  window) still aborts. Budgets follow the prompt: a review gets
  `_review_timeout(len(prompt))` (180s floor, +15s per 1k chars, 780s
  ceiling), E2E generation 240s.
- **A failed attempt leaves a trace on the issue** (`ATTEMPT_MARKER` comment,
  `agents/dev._note_failed_attempt`), and the picker reads those back: a
  sub-task that failed in an earlier cycle goes behind its untried siblings
  from the first iteration. The learned CLI timeout floor is also kept per
  workspace across cycles (`tools/claude._REPO_FLOORS`). Before both, every
  self-cycle spent its first sixteen minutes re-timing-out on #89 (#99).
- **A story closes when its last sub-task merges**
  (`techlead.close_finished_stories`, after both merge paths): a merged PR
  closes its task, and nothing closed the story above it — #344 and a
  dozen older stories sat open "in-progress" on concert-tour-app. **A
  parent is matched exactly** (`tools/github.is_child_of`/`parent_of`):
  "Parent: #32" is a substring of "Parent: #321", and on TheSwarm (issues
  #1-#230) a Play on #22 took #220-#229's children.
- **A sub-task waits for what it depends on** (`Breakdown.depends_on`,
  earlier positions only → "Depends on: #N" on the issue →
  `dev.depends_on`). Both pickers leave a task alone while a dependency is
  still open — claimed by a sibling Dev, in review, or not started. At
  width 2 the first two ready siblings used to start together and write
  each other's code (#322/#323 in 9d3174f41829; #325 never merged).
  Dependencies wait for a *merge*: on SELF_REPO, where approved PRs merge
  only at the end of the cycle, a dependent task waits for the next cycle.
- **The Dev is told about its siblings' open PRs** (`_sibling_prs`: title +
  files, in the prompt above the `ALREADY_SATISFIED` rule). Four sub-tasks
  of one story built in parallel each re-implemented the others' work
  (#104/#105/#108/#109). Their branches are still not in the checkout — the
  human who merges must still pick the complete one and close the rest.
- **QA starts a target the way it declares**, all under one `demo:` key in
  the target's `theswarm.yaml` (`agents/qa.py`): `command` / `env` — how to
  launch it and the scrubbed environment (only `PATH`/`HOME`/… plus `env`
  reach the process, never this instance's tokens) (`_demo_launch`, #110);
  `ready_seconds` — the readiness wait, in place of the 30s default
  (`_demo_ready_seconds`); `pages` — the paths walked for screenshots and the
  video, in place of the guessed `/`, `/docs`, `/health` (+ discovered
  routers) (`_pages_to_capture`); `setup` — shell commands run once per
  workspace before the first launch, each on its own 300s budget, same
  scrubbed environment, a failing one logged and skipped (`_run_demo_setup`).
  Without a declaration: `uvicorn src.main:app`, the guessed page walk, no
  setup. TheSwarm declares `python -m theswarm serve --port {port} --db
  {tmp}/demo.db` with `SWARM_AUTH_DISABLED=1`, `ready_seconds: 90`,
  `pages: ["/", "/r/jrechet/theswarm"]` (its own `/docs` 404s, #144), and
  `setup: ["bash scripts/build-css.sh"]` — the QA workspace is a plain clone
  and `static/v2/app.css` is generated, not checked in, so V2 pages rendered
  unstyled (Times, blue links) until this ran first. **The captures run in
  two lanes, side by side** (`qa.run_captures`, V2 M5b): the screenshot
  walk on `e2e_port()+1` and the video walk on `+2` each launch their own
  demo server and read nothing of each other, so QA spends the longer of
  the two. `SWARM_QA_CAPTURE_CONCURRENCY` (default 2: two demo servers and
  two browsers in a 2 GB container) — set it to 1 on a heavy target, or
  when a cycle's QA dies of memory. The per-story captures read
  `story_preview_urls`, which nothing sets yet: they are no-ops.
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
- **The host's Claude Code hooks fired inside every `claude -p` the swarm
  launched** — closed by the SDK's `setting_sources=[]` (M1), and the CLI
  backend is gone since M7 (2026-09-25); kept here for the parser rules it
  left. A `Stop` hook that dictates an end-of-session checklist made
  the reviewer spend its *last* message refusing that checklist — and
  `--output-format json` keeps only the last message. Cycles 3–4 of the
  local series (2026-09-20) filed `COMMENT` on reviews that had actually
  concluded `REQUEST_CHANGES`, and one bare `APPROVE` inside such prose was
  taken as a sign-off. Two hooks were removed (`~/.claude/hooks/deploy-guard.sh`
  and the project-local `.claude/hooks/session-wrap.sh`); a *bare* salvaged
  APPROVE is now downgraded to COMMENT while a labelled `Decision: APPROVE`
  still counts (#167). Emptying `~/.claude/CLAUDE.md` alone was not enough.
- **`find_system_python` honours the target's `requires-python`** (#167). On a
  host with a 3.11 ahead of a 3.12 on PATH the editable install refused, every
  test file errored on import, and the Dev read 165 import errors as a red
  suite: two Ralph rounds that wrote nothing and a PR claiming "Some tests
  failing". A failed install is now `tests_unavailable` carrying pip's
  `ERROR:` line, for the Dev and for QA alike (#166).
- **`commit_all` answers "did *we* commit", not "is there work"** (#167). With
  `acceptEdits` Claude committed, pushed and opened PR #165 by itself; seven
  minutes later the harness read "Nothing to commit" as "no file changes
  produced", filed a false failed-attempt note on the issue and reported
  `prs []`. `get_diff_stat` against main is the truth, whoever committed.
- **A review call could be granted 780s inside a 300s phase** — the phase
  timeout fired first, every time (#167). `techlead_review` is 30 min and
  `tests/test_review_budget_fits_its_phase.py` keeps the invariant. Review
  calls on this repo still time out now and then (three of seven local
  cycles): `_review_timeout` may under-estimate for this size of diff.
- **The Dev's gate runs only the tests its own diff touches** (#171). The
  whole suite needed QA's 900s here, and the Ralph retry runs it twice — one
  iteration reached an hour; at 120s the gate never measured anything on
  this repo. An unreadable diff falls back to the whole suite; a diff that
  maps to no test is `tests_unavailable`. `dev_iter` is 40 min, bounded on
  both sides by tests (`test_persisted_timeout_floor.py`,
  `test_dev_iteration_budget.py`).
- **QA picks a free base port** (#170). `E2E_PORT = 8000` was hardcoded and a
  stray `solana-te` held it on the owner's laptop: the readiness probe read a
  flat 400 for 90s and `e2e=0(pass)` for four cycles while 8001/8002 worked.
  The port is chosen once per process because the generated E2E file bakes
  it into its URLs. Until 2026-09-25 the prompt never *told* it: `{{port}}`
  in a `.format` template is `{port}` afterwards, the `.replace` that
  followed matched nothing, and the model guessed 8000 — right on prod by
  luck, wrong anywhere the port moved.
- **QA runs the E2E file it wrote, and repairs it once** when not one test
  sets up (every test an error, none passed or failed). The file is written
  blind; two cycles in five on 2026-09-25 reported `0 passed, 0 failed, 24
  errors` in under two seconds against a server answering 200. The repair
  call gets pytest's lines and the file, keeps every assertion, and the
  rerun is the verdict (`e2e_repaired_from` on the report card). A failed
  *assertion* is a verdict on the target and is never repaired.
- **On SELF_REPO approved PRs merge at the end of the cycle** (#173), after
  QA and the report — never in the review phase, whose redeploy would end the
  cycle. A merge that fails stays open (#164 became unmergeable the moment its
  companion #165 landed). **Not yet exercised by a real cycle** as of
  2026-09-22: cycle 7 approved nothing.
- **0% coverage under a passing suite is `not_run`, not `fail`** (#175):
  `num_statements == 0` means nothing was instrumented. Absent is not zero —
  a report without the field keeps its percentage.
- **V2 runtime (docs/plans/2026-09-v2-runtime.md) — M0 landed the Agent SDK
  probe.** `claude-agent-sdk` wheels bundle their own Claude Code binary
  (217 MB on linux x86_64; the npm install of Claude Code left the image
  in M7, 2026-09-25) and authenticate
  exactly like `claude -p`: the mounted `~/.claude` session in prod,
  `CLAUDE_CODE_OAUTH_TOKEN` on a laptop. Every child env — CLI or SDK — goes
  through `tools/claude._child_env`, which strips `ANTHROPIC_API_KEY`: in the
  binary's precedence a key outranks both the token and the session, so one
  left behind moves the cycle to per-token billing without a word. **For the
  SDK, omitting is not stripping**: `ClaudeAgentOptions.env` is merged *over*
  the parent's `os.environ`, so the key must be overridden to `""`
  (`_sdk_child_env`) — measured 2026-09-23, omission answered
  `apiKeySource: ANTHROPIC_API_KEY`, the empty override `none`.
  `python -m theswarm validate` runs a one-turn probe and prints who answered
  (`identity=subscription` is the only acceptable value); it is skipped when
  `SWARM_CLAUDE_BACKEND=api`, the test suite's default.
- **V2 runtime M1 — the SDK backend (`SWARM_CLAUDE_BACKEND=sdk`, set in
  `docker-compose.yml`).** Same `ClaudeCLI.run` contract, a message stream
  instead of one envelope. The call's *profile* is read off its two
  arguments: `acceptEdits`+workdir = edit (Dev), workdir alone = read (QA,
  PO), none = text (review, breakdown, memory). **The permission policy
  lives in a PreToolUse hook** (`tools/claude.decide_tool_use`), not in
  `allowed_tools`/`can_use_tool` alone: a tool listed in `allowed_tools` is
  auto-approved *before* `can_use_tool`, and reads inside the project never
  ask at all — the SDK says so itself (`CanUseToolShadowedWarning`). Only a
  hook sees every call; measured 2026-09-23: `Read /etc/hostname`, `cat
  .env`, `git push` refused, the fix and `pytest` allowed. Bash is not
  path-confined (`cat /etc/hostname` runs) — the deny list is pushes, `gh`,
  `.env`, `git config`/`remote`. A timeout is **resumed**
  (`resume=session_id`, `SDK_CONTINUE_PROMPT`) with the grown budget, never
  re-prompted from scratch while the session exists. Every call checks the
  init message's `apiKeySource` and refuses to run on an API key (I1). No
  `setting_sources` at all: the target repo's `.claude/settings.json` could
  carry the same Stop hook that voided the reviews. **`auto` is sdk →
  api** (M1 flipped it SDK-first after three green harness cycles; M7
  retired the CLI leg after fourteen prod cycles on the SDK): a quota is
  fatal everywhere, a spent SDK timeout (`SDKTimeoutError`, a
  `RuntimeError`) is not spent a second time, and any other SDK failure
  goes to the API only with a usable key — otherwise its own error
  surfaces. The way back from the SDK is a revert of M7b (#203);
  prod pins `sdk` in `docker-compose.yml`.
- **V2 runtime M2 — one OpenTelemetry trace per cycle, in Seq.** Root span
  `cycle` (`api.py`), a span per phase (`cycle._run_phase`), per graph
  node (`agents/base.traced_node`, every `add_node`), per Claude call
  (`tools/claude.ClaudeCLI.run`, with backend, model, profile, tokens,
  cost, turns, session). Exported to `$SEQ_URL/ingest/otlp/v1/traces`
  (Seq 2025.2 on jrec.fr); log events carry `@tr`/`@sp` so a line and its
  trace meet. The trace id rides `CycleStarted` into the `cycles` row
  (`trace_id`, migration v027) and the theater links it (`trace ↗`).
  A new node needs nothing: `traced_node` wraps at `add_node`. Without
  `SEQ_URL` spans exist (ids for logs) and go nowhere.
- **V2 runtime M3 — no decision of code is read out of prose.** The
  breakdown, the review verdict and the Dev's outcome are asked for as
  validated JSON (`agents/schemas.py`: `Breakdown`, `ReviewVerdict`,
  `DevOutcome`; `ClaudeCLI.run(output_schema=…)` → `ClaudeResult.structured`)
  and the SDK re-prompts on a mismatch; a schema asked for and not
  answered is a failed call (skipped, never guessed). The Dev's
  `--- FILE:` fallback has a structured twin (`DevOutcome.files`,
  `_write_outcome_files`, same path rules); `already_satisfied` is a
  `status`, read only from the structure when there is one, and still only
  believed on a clean tree (I3). The text parsers (`_parse_review`,
  `_parse_tasks_json`, `ALREADY_SATISFIED_RE`) stay as the CLI backend's
  fallback until M7 — fakes in older tests return plain `SimpleNamespace`
  results, so read `structured` with `getattr(result, "structured", None)`.
- **V2 runtime M4 — the cycle is a durable LangGraph** (`cycle_graph.py`;
  `run_daily_cycle` keeps its contract and runs it). Nodes = the phases
  (`prepare → po_morning → techlead_breakdown → dev_iter ⇄ techlead_review
  → dev_loop_end → qa → po_evening → merge_held → finish → cycle_log`),
  checkpointed after each one (`durability="sync"`) on the server's
  `AsyncSqliteSaver` — its own file `cycle_checkpoints.db` and connection,
  never the app's shared one (I10); in memory for the CLI and the gateway.
  Thread id = cycle id. `run_daily_cycle(resume=True)` continues from the
  node after the last that finished; the boot resumer runs it on the
  interrupted cycle's thread inside a new tracker record
  (`_run_api_cycle(resume_cycle_id=…)`); a cycle with no graph thread
  (pre-M4) or another `CYCLE_STATE_SCHEMA_VERSION` is refused
  (`CycleNotResumable`), never misread. **State holds values, never
  objects**: the GitHub client, the Claude wrapper, the progress callback
  and the watchdog travel in `Runtime[CycleRuntime]` (context, not
  checkpointed). `attempted_tasks` is passed by reference to the picker
  *and* returned — an in-place mutation is invisible to a checkpoint. The
  budgets and exceptions moved to `cycle_budgets.py`; `theswarm.cycle`
  re-exports them and the graph reads `PHASE_TIMEOUTS`/`MAX_DEV_ITERATIONS`
  off `theswarm.cycle` at call time, so tests keep patching them there.
  A node re-run after a crash between effect and checkpoint is the normal
  case: keep every node safe to repeat (learnings and the cycle log are
  separate nodes for that reason). The phase-checkpoint table
  (`on_checkpoint`) still feeds the V1 cycles page until M7. **Agent graphs
  run detached** (`cycle_graph._invoke_agent`: a fresh contextvars.Context,
  the OpenTelemetry context re-attached): a compiled graph invoked inside a
  node inherits the parent's checkpointer and its state carries live
  clients — the first prod cycle on the graph (ddd989b4e51e) died in
  po_morning on "Type is not msgpack serializable: GitHubClient".
  `checkpointer=False` on the agent graphs is kept too, but alone it trips
  LangGraph under `durability="sync"` (`_put_checkpoint_fut`). A resume
  mid dev-loop hands back the tasks the dead iteration claimed first.
  **A resumed cycle has a new id**: the reap marks the old row `failed`
  and the continuation runs under a fresh tracker record, so the old row
  carries `resumed_as` (migration v029, set by `server._launch_resume`),
  `/api/cycles/{old}` returns it, the harness follows it (and waits out the
  404s of a stop-first rolling update instead of calling the cycle lost),
  and `/c/{old}` redirects to the continuation's theater. The
  continuation is started on the pinned issue its checkpoint kept
  (`CycleState.target_issue`: the first resume, 83b584194589, came back
  untargeted and its Dev built #212 from the backlog). The continuation's
  trigger is `auto-resume:1` — before, every cycle row said `web` and the
  one-resume cap (`MAX_RESUME_DEPTH`) never held.
  `/api/cycles/{id}` also carries the tracker's `result` on the database
  answer: the harness read cost, backend and review decisions from it, and
  every eval run before this scored them empty.
- **V2 runtime M5a — the target runs in its own venv, inside its
  workspace.** `agents/base.ensure_target_venv` builds `<workspace>/.venv-swarm`
  once (`uv venv --seed`, the binary is in the image; `python -m venv`
  without it), from the interpreter the target's `requires-python`
  accepts; `find_system_python` then answers that venv, so Dev and QA
  install and test with the same one and the container's system python is
  never mutated again. Off in the suite (`SWARM_TARGET_VENV=0` in
  conftest) — a real venv per tmp workspace is seconds per test. **Runtime
  artifacts never reach a commit**: `clone_repo` writes `.venv-swarm/`,
  `.worktrees/`, `test.db*`, coverage output into the clone's
  `.git/info/exclude` (`tools/git.exclude_locally`, best effort), which
  `git add -A` and `git clean -fd` both honour — the old "known gap" is
  closed without touching the target's `.gitignore`. **Cycles across
  repositories share one bound**: `SWARM_MAX_CONCURRENT_CYCLES` (default
  1, `cycle.cycle_slot`), held with the repo lock by the API and the
  gateway; a second repo now queues like a second cycle on the same repo.
  **M5b, first half — one git worktree per Dev task**
  (`tools/git.add_worktree`, `SWARM_DEV_WORKTREES`, on by default, off in
  the suite whose Dev fakes mock `create_branch`): the Dev implements,
  gates, commits and pushes in `<clone>/.worktrees/<branch>`, the clone
  itself stays on main, and the worktree is retired once the PR is open
  (the branch stays), on no change, on failure, and at `dev_loop_end` for
  stragglers. A worktree uses its clone's `.venv-swarm` (`base.venv_home`,
  and the Claude child's PATH) — one install per clone, not per task.
  Worktree bookkeeping is serialised per clone. A retry of a task whose
  worktree a crash left behind drops it first (git refuses a second
  checkout of a branch). **Second half — parallel sub-tasks**
  (`SWARM_DEV_PARALLELISM`, default 1 = the single path, unchanged): above
  1 a Dev iteration runs that many Dev graphs at once
  (`cycle_graph._dev_iter_parallel`), each on its own task and worktree.
  The pickers take turns behind one lock and skip what a sibling claimed
  (`pick_lock`, `claimed_tasks` in `AgentState` — LangGraph drops input
  keys a schema does not declare): the in-progress label is not a lock.
  A branch that raises is its task's failure (already handed back), not
  the iteration's; a quota still ends the cycle. Side by side, each
  worktree has its own `.venv-swarm` — an editable install into a shared
  one would make one task test the other's code. Run once in prod at
  width 2 (cycle `9d3174f41829`, 2026-09-25, `docker service update
  --env-add`, then `--env-rm`): two worktrees five seconds apart, each
  building its own venv, three PRs, harness PASS, TheSwarm's venv
  untouched. Prod stays at 1 until the owner chooses otherwise.
- **V2 runtime M6 — the harness is an eval suite.** `evals/<target>.yaml`
  lists the canonical features (eleven on concert-tour-app since 2026-09-25: the first five were all built; `evals.exhausted` makes the harness warn when that happens again); `theswarm.evals`
  picks the feature of the day (rotation by day of year), scores a run
  (`passed` keeps its pre-M6 meaning — completed, a PR, nothing unbuilt —
  and the PR's CI, the review decisions, cost, duration, `within_cost`,
  `within_time`, `files_match` against the feature's globs, and the
  backend the cycle reports are their own fields) and reads the trend the
  repo page draws (`data-testid="evals"`, last 14 runs, per backend).
  `scripts/cycle_e2e.py --repo X` with no feature runs the day's; `--all`
  the series (a manual dispatch, `all=true`); a typed `--feature` runs as
  before. A failed run posts to Mattermost when the workflow has the token
  (`MATTERMOST_URL`/`MATTERMOST_BOT_TOKEN`). **A deliberate regression**
  is one env var away: `SWARM_SDK_MAX_TURNS_EDIT=1` (also `_READ`, `_TEXT`;
  `tools/claude._max_turns`) caps the Dev's implementation at one turn —
  the eval suite must read the day as failed runs and recover once it is
  removed. **The scored record is posted
  to `POST /api/evals/runs`** (table `eval_runs`, migration v028) and the
  repo page reads the trend from there; the `docs/harness-runs.jsonl` line
  is still written, but it is not a delivery path to count on. On
  2026-09-23 the same step with the same token was refused at 14:37 ("Changes
  must be made through a pull request", run 35874015968) and accepted at
  15:33 (run 35882035360). `main`'s protection, read at 17:25, requires a PR
  but is not enforced on admins, so an admin token gets through; whether
  agent writes to main (daily report, memory save, cycle history, this
  line) should rely on that is an owner decision (plan section 8).
  **A feature already on main is `already_delivered`, not a failure.** The
  target keeps what the swarm merges, and the rotation gave every dispatch
  of a day the same feature: the fourth run of 2026-09-23 (cycle
  874f575645f2) asked for the city search two runs had merged, the Dev
  rightly closed #286-#288 as already satisfied, and the harness printed
  "no pull request produced" and a regression. The cycle result now lists
  those sub-tasks (`already_satisfied`); a completed cycle with no PR,
  nothing open and that list non-empty scores `outcome:
  already_delivered` — `passed` stays False, it is never a regression,
  never the run a new one is compared with, and not counted in the pass
  rate. A bare dispatch skips the features whose last run built them or
  found them built (`evals.next_feature`), reading the history from the
  API first: the checkout is main *at dispatch*, and a run queued behind
  another lacks that run's line — which is also why two runs' appends
  conflicted in the publish step until `.gitattributes` gave the file
  `merge=union`.
- **V2 runtime M8 — the GitHub-native doors.** The webhook route
  (`/webhooks/github`, outside the auth wall) is installed **only** when
  `SWARM_WEBHOOK_SECRET` is set (server.py; the repository webhook on
  GitHub signs with the same secret — a manual step, like the OAuth App);
  without it the route answers 501. Both doors are owner-only
  (`SWARM_OWNER_LOGIN`), allowed-repo-only, and one trigger per repo per
  minute. **A label** (`swarm:go`, `SWARM_GO_LABEL`) on an issue starts a
  targeted cycle exactly like ▶ Play (`routes/v2.start_targeted_cycle`,
  shared) and is taken off again. **`@swarm <instruction>`** from the owner
  on a pull request reaches the Dev the way a review's REQUEST_CHANGES
  does: a `CHANGES_MARKER` note on the task issue, `status:ready`, a cycle
  pinned to the task; the Dev resumes the PR's branch and the review runs
  again. A PR without `[#N]`/`Closes #N` is answered, not run. **The
  TechLead's verdict is a commit status** `theswarm/review` on the PR's
  head (success / failure; a PAT can set statuses where a Check needs an
  App), best effort. `/r/{owner}/{name}/memory` renders
  `AGENT_MEMORY.jsonl` by category, linked from the repo page.
- **Running the swarm on itself from a laptop**: use
  `scripts/local_cycle/run-targeted.sh <issue>`, never `run-cycle` — the daily
  breakdown walks the whole backlog at ~220s an issue inside a 600s phase.
  Series of 2026-09-19→22: `docs/handoffs/2026-09-22-local-cycle-series-and-v2-handoff.md`.
