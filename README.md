# TheSwarm

**Describe a feature on one of your repositories, press ▶ Play, watch four agents build it, get the demo.**

A Product Owner, a Tech Lead, a Developer and a QA — LangGraph state graphs on the Claude Agent SDK, running on your Claude subscription — turn a feature written in plain English into a GitHub issue, a breakdown, pull requests reviewed and merged, and a recorded demo of the feature running, with a verdict on whether the running app agrees with the tickets.

Measured, not promised: since 2026-10-01 the production instance has built one new feature a day on [concert-tour-app](https://github.com/jrechet/concert-tour-app) with nobody at the keyboard — five features in five days, all built, four of them *verified on the running app* — at about $1.70 and 20 minutes each.

```
you: "Reschedule a concert — PATCH /api/v1/concerts/{id} with a new date_time, 422 for a date in the past …"
      │
      ▼  ▶ Play
   PO ──── TechLead ──── Dev ──── TechLead ──── QA ──── PO
   issue   breakdown    PRs      review       demo    report
                         ▲         │ merge
                         └─────────┘
      │
      ▼
   🎬 "The demo is ready — watch it"   (on the issue, with the behaviour gates)
```

---

## The flow

1. **Sign in** — the access key, or "Sign in with GitHub" for the owner.
2. **Pick a repository** (`/`) — the repositories your `GITHUB_TOKEN` can see, plus the ones already registered.
3. **Write the feature** (`/r/{owner}/{name}`) — the first line becomes the issue title; the composer creates the GitHub issue and highlights it on the board.
4. **▶ Play** — a cycle pinned to that issue starts: the Tech Lead breaks it into sub-tasks (each shipping its own tests), the Developer builds them in parallel git worktrees, the Tech Lead reviews and merges on green CI, QA writes and runs E2E tests of the feature, plays the feature's own requests on a seeded demo server, records the pages and the video, and the PO reports.
5. **The theater** (`/c/{cycle_id}`) — the four agents live, the breakdown ticking off, the activity feed; it ends on the demo card.
6. **The demo** (`/demos/{report_id}/play`) — stories, quality gates, screenshots, the video. The issue gets a comment: *🎬 The demo is ready — watch it*, with what was built and the behaviour gates.

What "verified" means: QA's tests *of the feature* passed against the running app, every page the PRs added answered, and the feature's own requests (a POST, a PATCH, a DELETE…) answered 2xx on the demo server. A build the running app contradicts is reported as *broken*; a test that was itself wrong is triaged and never counted against the app.

---

## Quickstart (a laptop)

### Prerequisites

- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/)
- A Claude subscription: run `claude setup-token` once (a token valid for a year), or be logged in to Claude Code on this machine (`~/.claude`)
- A GitHub token that can read and push to the target repository
- A target repository with a Python test suite (`requirements.txt` or a `pyproject.toml` with a `dev` group) — see *What a target declares* below

### Install

```bash
git clone https://github.com/jrechet/theswarm.git
cd theswarm
uv sync --dev
bash scripts/build-css.sh      # the V2 stylesheet is generated, not committed (fetches the pinned Tailwind binary into ./tmp/bin)
```

### Configure

```bash
# .env
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...   # from `claude setup-token`; omit if ~/.claude is logged in
GITHUB_TOKEN=ghp_...
SWARM_AUTH_DISABLED=1                      # local only: opens the dashboard to anyone who can reach it
```

```bash
uv run python -m theswarm validate
#   Agent SDK: ok — identity=subscription model=claude-haiku-4-5 claude_code=2.1.280 cost=$0.0479 …
# Validation passed.
```

`identity=subscription` is the only acceptable answer: the swarm never runs on a per-token API key by accident (every child process has `ANTHROPIC_API_KEY` stripped).

### Start

```bash
uv run python -m theswarm          # http://localhost:8091
```

### First feature

Open `http://localhost:8091/`, pick the repository, describe the feature — first line the title, then what the API or page must do — and press **▶ Play**. The theater opens; a feature of two or three sub-tasks takes 10–20 minutes. When the demo card appears, *Watch the demo →*.

---

## What a target declares

TheSwarm works on a plain Python web repository. Three things make the demo and the verdict better:

**`theswarm.yaml`** in the target, a `demo:` block telling QA how to run the app for its captures — concert-tour-app's:

```yaml
demo:
  command: "{python} -m uvicorn src.main:app --host 127.0.0.1 --port {port}"
  env:
    DATABASE_URL: "sqlite:///{tmp}/demo.db"   # a database of its own per demo server
  pages: ["/dashboard", "/"]                   # walked for the screenshots and the video
  seed: ["{python} scripts/seed_demo.py"]      # run once the server answers, so the pages have data
  # also: ready_seconds, setup (commands run once per workspace)
```

Without it: `uvicorn src.main:app`, a guessed page walk, no seed. The pages the cycle's PRs add join the walk automatically, read off the diffs.

**Labels** — issues flow `status:backlog → ready → in-progress → review → closed`; the Developer takes `role:dev` + `status:ready`. The composer and the Tech Lead set them; you never have to.

**`AGENT_MEMORY.jsonl`** — what the agents learned about the repository, committed to it and shown at `/r/{owner}/{name}/memory`.

The target's dependencies are installed in a venv of its own inside the workspace (`.venv-swarm`); TheSwarm's own environment is never touched.

---

## The other doors

| Door | How |
|------|-----|
| **A label** | Put `swarm:go` on an issue (owner only): a cycle pinned to it starts, the label is taken off. Needs `SWARM_WEBHOOK_SECRET` and a repository webhook signed with it. |
| **`@swarm <instruction>`** on a pull request | The instruction reaches the Developer like a review's "changes requested": it resumes the PR's branch and the Tech Lead reviews again. |
| **Headless API** | `POST /api/cycle {"repo": "owner/name", "issue_number": 42}` → `{"cycle_id"}`; `GET /api/cycles/{id}`; `POST /api/cycle/{id}/cancel`. With `Authorization: Bearer $SWARM_ACCESS_KEY`. |
| **The probe** | `POST /api/claude/probe` — can Claude answer right now? A standing wall (expired credentials, an exhausted subscription window) answers for free; otherwise one short call does. The harness asks it before opening anything. |
| **Liveness** | `GET /health` — `claude: ok | quota_wall | auth_expired`, with when the window reopens or why the credentials were rejected. |

---

## How it is measured

- `evals/<target>.yaml` lists the canonical features (45 on concert-tour-app). The harness (`scripts/cycle_e2e.py --repo owner/name`, run daily at 07:00 UTC by `harness.yml`) asks for the next feature the target does not have, waits for the cycle, and scores it: built or not, the behaviour verdict, the PRs' CI, the review decisions, cost, duration, the files touched. A feature already on the target is `already_delivered`; a run the credentials or the subscription window ended is `interrupted` — neither is a regression.
- Every run is posted to `POST /api/evals/runs`; the repository page draws the trend (built / verified / interrupted, cost and duration averages) and `docs/harness-runs.jsonl` keeps the history.
- Every change to the swarm ships with a recorded demo — `docs/demos/README.md` indexes them; `scripts/record_v2_demo.py` films a real Play end to end.

---

## Operations

### The auth wall

The dashboard fails closed. Set `SWARM_ACCESS_KEY` (the login form, and the Bearer token for `/api/*`) and `SWARM_SESSION_SECRET` (sessions survive a restart); `SWARM_OWNER_LOGIN` plus a GitHub OAuth App (`/setup/github-oauth`) adds "Sign in with GitHub" for that one login. `SWARM_AUTH_DISABLED=1` opens everything — local development and tests only.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `GITHUB_TOKEN` | **Required.** Read the backlog, push branches, open and merge PRs (injected per git command, never written to `.git/config`). |
| `CLAUDE_CODE_OAUTH_TOKEN` | The subscription token from `claude setup-token`; without it the mounted `~/.claude` session answers. An auth failure retries once without the token. |
| `SWARM_ACCESS_KEY`, `SWARM_SESSION_SECRET` | The auth wall (see above). |
| `SWARM_AUTH_DISABLED` | `1` opens the wall — local only. |
| `SWARM_OWNER_LOGIN`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | Sign in with GitHub, for the owner (default login `jrechet`). |
| `EXTERNAL_URL` | The public URL: the demo link posted on the issue is useless without it. |
| `BASE_PATH` | Reverse-proxy prefix (prod runs under `/swarm`). |
| `SWARM_PO_GITHUB_REPOS` | Comma-separated repositories allowed at boot; the picker registers more. |
| `SWARM_WEBHOOK_SECRET`, `SWARM_GO_LABEL` | The GitHub doors (`swarm:go` by default). Without the secret the webhook route answers 501. |
| `SWARM_CLAUDE_BACKEND` | `auto` (default: the SDK, the API only as a fallback with a usable key), `sdk`, `api`. |
| `ANTHROPIC_API_KEY` | The API fallback only — a real `sk-ant-api` key; an `sk-ant-oat` token is ignored here. Never reaches an agent's child process. |
| `SWARM_DEV_PARALLELISM` | Sub-tasks built side by side (prod runs 2); a chained breakdown runs in order. |
| `SWARM_QA_CAPTURE_CONCURRENCY` | QA's capture lanes (default 2: two demo servers and two browsers). |
| `SWARM_MAX_CONCURRENT_CYCLES` | Cycles across repositories (default 1); one per repository always. |
| `SWARM_WORKSPACE_DIR` | Where targets are cloned (default `~/.swarm-workspaces`). |
| `SEQ_URL`, `SEQ_API_KEY` | Logs and one OpenTelemetry trace per cycle (the theater links it). |
| `SWARM_VAULT_MASTER_KEY`, `MATTERMOST_BOT_TOKEN`, `SWARM_PO_MATTERMOST_TOKEN` | The legacy Settings page and the Mattermost persona. |

`python -m theswarm validate` checks them and probes the SDK.

### Storage

`~/.swarm-data/`: `theswarm.db` (SQLite — projects, cycles, reports, eval runs, memory), `cycle_checkpoints.db` (the durable cycle graph, on its own connection), `artifacts/` (screenshots and videos, served at `/artifacts/…`). `~/.swarm-workspaces/`: one clone per target, with its `.venv-swarm` and the task worktrees.

### Deployment

CI builds the image to GHCR; a push to `main` deploys it on Docker Swarm behind Traefik (`docker-compose.yml`, `cd.yml`). The deploy waits for a running cycle to finish (up to 30 minutes); a cycle a restart does interrupt is resumed by the new container from its last finished phase. The container mounts the host's `~/.claude` as the session fallback and runs the SDK backend (`SWARM_CLAUDE_BACKEND=sdk`). Production: <https://bots.jrec.fr/swarm>.

---

## Legacy

The V1 surfaces — the multi-role dashboard, the per-role pages, the Mattermost persona (`@swarm-po`), the CLI cycles (`python -m theswarm cycle --project …`) and schedules — are kept and reachable under **Legacy**, not developed. The V2 flow above is the product.

---

## Documentation

- `AGENTS.md` — the operating manual: architecture, conventions, and every landmine learned in production, with the cycle that taught it.
- `docs/ARCHITECTURE-V2.md`, `docs/plans/2026-09-v2-one-flow.md` (the surface), `docs/plans/2026-09-v2-runtime.md` (the engine: SDK backend, durable graph, isolation, traces, evals).
- `docs/demos/README.md` — one recorded demo per change; `docs/DEPENDENCIES.md` — the external dependencies, credentials and CDNs.

---

## Architecture

Clean Architecture, two packages in `src/`: `theswarm` (agents, cycle, web) and `theswarm_common` (Mattermost adapter, config loader).

```
src/theswarm/
├── agents/            # po, techlead, dev, qa (+ qa_feature_pages, qa_feature_calls, schemas)
├── cycle_graph.py     # the durable LangGraph: prepare → po → breakdown → dev ⇄ review → qa → report
├── tools/             # claude (Agent SDK backend, walls, probe), github, git, github_app
├── evals.py           # the eval manifest, scoring, trend
├── domain/ application/ infrastructure/   # entities, CQRS + services, SQLite repos + recorder
└── presentation/
    ├── web/           # FastAPI + Jinja: V2 routes (/, /r/…, /c/…, /demos/…), the auth wall, V1 under Legacy
    └── cli/
```

The cycle is one LangGraph checkpointed after every node; agent graphs run inside the nodes; state holds values only, the clients travel in the runtime context. The Claude backend is the Agent SDK with a PreToolUse policy hook deciding what the agents' Bash may run.

---

## Testing

```bash
uv run pytest tests/ -v --tb=short --ignore=tests/e2e -p no:playwright   # 3 700+ tests, ~3.5 min
uv run pytest tests/test_agent_state_schema.py -p no:playwright          # after touching agents/*.py
uv run pytest tests/e2e/ -v                                              # needs a running server
```

`asyncio_mode = "auto"`, `respx` for HTTP mocks, tests by layer under `tests/`. The suite never launches the real Claude binary.

---

## License

MIT
