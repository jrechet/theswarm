# External dependencies

Every external dependency is a shared decision (owner rule). This map is the
at-a-glance view: who controls it, what it costs, what credential it holds,
how replaceable it is, and whether the decision is settled.

```mermaid
flowchart LR
    subgraph Serving["jrec.fr (self-hosted, owner-controlled)"]
        SWARM[TheSwarm container]
        TRAEFIK[Traefik]
        SEQ[Seq logs]
        MM[Mattermost]
    end

    subgraph GitHub["GitHub (Microsoft)"]
        GHREPOS[Repositories & issues]
        GHAPP[GitHub App - theswarm-jrec]
        GHCR[GHCR image registry]
        GHA[GitHub Actions CI]
    end

    subgraph Anthropic["Anthropic"]
        CLI[Claude Code CLI - subscription]
        SDK[Claude Agent SDK - same subscription, V2]
        API[Claude API - fallback]
    end

    subgraph Buildtime["Build-time only"]
        TW[Tailwind binary - pinned v4.3.3]
        PYPI[PyPI packages via uv.lock]
        PLEX[IBM Plex fonts - vendored in repo]
        GEIST[Geist fonts - vendored in repo, OFL]
    end

    USER((Owner)) -->|OAuth sign-in| GHAPP
    TRAEFIK --> SWARM
    SWARM -->|installation tokens 1h| GHAPP
    GHAPP --> GHREPOS
    SWARM -->|CLI first| CLI
    SWARM -->|V2: SDK first| SDK
    SWARM -.->|fallback| API
    SWARM -->|logs + OTLP traces| SEQ
    SWARM -.-> MM
    GHA -->|push image| GHCR -->|pull| SWARM
    TW -.->|app.css baked into image| SWARM
```

| Dependency | Controlled by | Cost | Credential | Risk | Replaceable by | Decision |
|---|---|---|---|---|---|---|
| GitHub (repos, issues, PRs) | Microsoft | free tier | — | platform lock-in, core to product | GitLab port (large) | ✔ settled (core) |
| **axe-core, through `axe-playwright-python`** (dev dependency, M7) | Deque (MPL-2.0) / pamelafox (MIT) | free | — | runs only in the E2E smoke walk in CI, never shipped; a false positive fails a PR's smoke job | drop the axe test, keep the walk | ⏳ owner's decision (proposed 2026-10-07) |
| **ssh from the DevOps persona to jrec.fr** (D1 reads: the CI slot's owner files, `df`, the load; **D3 writes, on the owner's click only**: `sudo rm -rf <slot>`, `docker service update --force <runner>`, `docker service update --image <registry>:<sha> <service>` — the three `KINDS` of `domain/ops/proposals.py`, nothing else) | Owner | free | the ambient ssh key — the laptop's today; **prod's container has none**, so its Ops card reads the host as "not reachable from here" and an approved proposal there records `failed: not reachable from here` until a key is mounted | a mounted key reaches the host as `debian` (passwordless sudo, docker group); a `command=` restriction in `authorized_keys` must allow the read script and the three KINDS commands, or D3 stays read-only on prod | the host's facts over a bind mount of `/srv/gh-runner-work/ci-slots` instead of ssh; proposals approved from the laptop only | ⏳ owner's decision (proposed 2026-10-07, D3 2026-10-07) |
| **GitHub App `theswarm-jrec`** | **Owner's account** | free | private key + client secret, in Fernet vault | key leak → repo write access on installed repos only | static `GITHUB_TOKEN` (documented fallback) | ✔ owner, 2026-09-01 |
| GitHub Actions + GHCR | Microsoft | free tier | `GITHUB_TOKEN` (ephemeral) | CI outage blocks deploys | self-hosted runner exists | ✔ settled |
| Claude Code CLI (subscription) | Anthropic | owner's Max plan | OAuth session mounted in container | session expiry (seen 3×) → cycles fail | Claude API | ✖ retired in V2 M7 (2026-09-25): the SDK's bundled binary replaced it, Node left the image |
| Claude API | Anthropic | per-token | `ANTHROPIC_API_KEY` | spend without cap if primary silently fails | none (fallback) | ✔ settled |
| **Claude Agent SDK** (`claude-agent-sdk`, PyPI) | Anthropic | owner's Max plan (same identity as the CLI: `CLAUDE_CODE_OAUTH_TOKEN`, else the mounted session) | prod: the optional repo secret `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`, a year) first, the mounted `~/.claude` session as the fallback — the session died during the 2026-09-28 outage (2026-09-29) | the wheel bundles a 217 MB Claude Code binary (image size); Anthropic's terms allow *individual* subscription use only — never route other users through it | the Claude API with a usable key (`auto` falls back to it); the CLI backend was retired in M7 | ✔ owner, 2026-09-22 (V2 runtime, decision 1) |
| `opentelemetry-sdk` + `opentelemetry-exporter-otlp-proto-http` (+ protobuf, requests) | OSS (CNCF) | free | reuses `SEQ_API_KEY` | supply chain (pinned in uv.lock); exports only to Seq, already a dependency — no new service | log lines alone (spans off when `SEQ_URL` is unset) | ✔ owner, 2026-09-22 (V2 runtime, M2) |
| GitHub repository webhook (V2 M8) | Owner's repos on GitHub | free | `SWARM_WEBHOOK_SECRET` (repo secret → `.env`; the webhook on GitHub signs with the same value) | a public route, HMAC-checked; owner-only, rate-limited; off without the secret | ▶ Play in the UI (no webhook) | ✔ owner, 2026-09-22 (V2 runtime, M8) — the owner creates the webhook (issues, issue_comment) by hand |
| semgrep (PyPI, pinned `1.178.0`), run by QA through `uv tool run` | Semgrep Inc. (OSS engine, LGPL) | free | — | a ~71 MB wheel downloaded once into the uv cache on the data volume; `--config=p/owasp-top-ten` fetches the rules from semgrep.dev at each run; `--metrics=off` | skip the scan (`SWARM_QA_SEMGREP=0`) — the report then says `not_run` | ⏳ proposed by the agent 2026-09-25 (QA's scan never ran in prod: semgrep was not in the image) — owner to confirm |
| bandit (PyPI, pinned `1.9.4`), run by QA through `uv tool run` beside semgrep | PyCQA (OSS, Apache-2.0) | free | — | a small wheel downloaded once into the uv cache on the data volume; reads the target's `src/` only; no network at run time | skip it (`SWARM_QA_BANDIT=0`) — the gate then reads semgrep alone | ✔ owner's choice 2026-10-06 ("1: bandit") |
| pytest-playwright and pytest-cov (PyPI), installed by QA into the target's own `.venv-swarm` | pytest-dev (OSS, Apache-2.0 / MIT) | free | — | downloaded into the swarm-owned venv of the target's workspace when the target does not list them: pytest-playwright for the E2E run (since the E2E node existed), pytest-cov for the coverage gate (2026-09-25); never into a system python or TheSwarm's venv | without them E2E and coverage report `not_run` | ⏳ recorded by the agent 2026-09-25 (pytest-playwright was installed unrecorded before) — owner to confirm |
| `uv` binary, at runtime | Astral (OSS) | free | — | already in the build stage; now copied into the image to build the target's venv (`uv venv --seed`) — falls back to `python -m venv` when absent | `python -m venv` (slower) | ✔ owner, 2026-09-22 (V2 runtime, M5) |
| `langgraph-checkpoint-sqlite` (+ `sqlite-vec`) | OSS (LangChain) | free | — | supply chain (pinned in uv.lock); its own SQLite file, never the app's shared connection | LangGraph's in-memory saver (loses durability) | ✔ owner, 2026-09-22 (V2 runtime, decision 2) |
| Mattermost `chat.jrec.fr` | Owner | self-hosted | bot token | low — optional surface | disconnect | ⚠ 404 on boot, fix-or-drop pending — the host is right (Traefik router `Host(chat.jrec.fr)`), but service `mattermost_mattermost` has run no task since ~2026-05 (last task shut down, earlier ones failed unhealthy), so Traefik answers its own 404; the harness alert fails the same way (read 2026-09-24) |
| Seq `logs.jrec.fr` | Owner | self-hosted | API key | low | stdout logs | ✔ settled |
| Tailwind standalone binary | Tailwind Labs | free, MIT | — | build-time fetch from GitHub releases (pinned + no runtime presence) | hand-rolled CSS | ✔ owner, 2026-09-01 (V2 UI) |
| IBM Plex fonts | IBM (OFL) | free | — | none — woff2 vendored in repo, no CDN | system fonts | ✔ owner, 2026-09-01 (V2 UI) — leaves with V2 at V3 M6 |
| Geist + Geist Mono fonts | Vercel (OFL 1.1, `static/v3/fonts/LICENSE.txt`) | free | — | none — the two variable woff2 vendored from the `geist` npm package 1.3.1, no CDN | system fonts (the tokens are the look, not the face) | ✔ owner, 2026-10-06 (V3, "modern control room") |
| PyJWT + cryptography | OSS | free | — | supply chain (pinned in uv.lock) | — | ✔ owner, 2026-09-01 (App auth) |

**Not dependencies (by design):** no runtime CDN (fonts and CSS ship in the
image), no third-party analytics, no external database.
