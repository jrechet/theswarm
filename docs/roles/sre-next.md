# SRE / DevOps — NEW role

> Codenamed (e.g., `Otis`, `Freya`, `Rao`). Typically shared across projects initially; can be split when a project grows.

## Why this role

TheSwarm currently ships to PRs on `main`. Production deploy of TheSwarm itself runs via `docker stack up` on `jrec.fr`, monitored via Seq at `logs.jrec.fr`. No role owns the _operational_ story for the projects TheSwarm builds. Rollouts, observability, on-call, cost-of-infra, incident response all fall between the cracks.

## Responsibilities

### 1. Ship-to-prod pipeline

- Per project: declares how this project ships (GitHub Actions, Vercel, Fly, self-host, ...).
- Owns `.github/workflows/*` for the project's release track.
- Canary + progressive rollout strategy when applicable (feature flags, shadow traffic, staged rollout).

### 2. Observability baseline

- Every project must have: structured logs, at least 3 core metrics (RPS, error rate, p95 latency for web; job duration, failure count for jobs), one dashboard, one alert rule.
- For our stack: Seq + Grafana-style SSE panels on the dashboard.
- SRE seeds sensible defaults on project creation.

### 3. Incident response

- When a production error rate or alert fires, SRE opens an incident thread (dashboard + optional Mattermost/Slack fan-out).
- Incident lifecycle: detect → triage → mitigate → resolve → post-mortem.
- Post-mortem is a structured memory entry with causes, timeline, action items (themselves become stories to PO or issues to TechLead).

### 4. Cost watch

- Infra cost budgets per project; cloud API usage tracked where possible.
- Claude / Anthropic API cost per project + per cycle (already partially tracked). Fold into one view.
- Alerts when spend trajectory exceeds budget.

### 5. Secret & key rotation

- Owns `secrets.yaml` templates and rotation cadence.
- Detects long-lived tokens; schedules rotation stories.

### 6. Backup & restore drills

- Periodic restore drill for any project with persistent state.
- Documents RPO/RTO per project.

### 7. Infra-as-code custody

- Where infra lives: SRE owns the Terraform / docker-compose / systemd units / Kubernetes manifests.
- Plans changes with a diff; runs in a dedicated cycle type (`infra-cycle`) that does not ship app code.

## Interactions

- **← Dev.** Receives artifacts, deploys them.
- **← TechLead.** Receives dep upgrades with possible migration steps.
- **← QA.** Receives perf baselines + regressions to investigate.
- **→ PO.** Surfaces cost, reliability, and risk signals for prioritization.

## Memory patterns

- Per-project-per-SRE: `runbooks`, `incidents`, `alerts`, `slos`, `infra_costs`, `secrets_index`.
- Global: `cross_project/runbook_patterns`.

## Dashboard surfaces

- **Ops** page per project: SLO status, recent incidents, deploy history, open alerts.
- **Cost** panel per project (infra + AI).
- **Incident thread** UI with timeline, mitigations, post-mortem.
- **Secrets inventory** (names + rotation dates — never values).

## New tools

| Tool | Purpose |
|---|---|
| GitHub Actions API | Manage workflows |
| Seq API | Logs + alerts |
| `ssh` / `docker stack` (gated per environment) | Deploy on `jrec.fr` |
| Sentry / Glitchtip (optional) | Error aggregation |
| Cost APIs (Anthropic, Fly, Vercel) | Spend tracking |

## Success metrics

- Deploy success rate ≥ 98%.
- MTTR on P1 incidents < 1h (for solo-dev scale; tighter when team grows).
- SLO attainment ≥ 99% when declared.
- Secret age P95 < rotation interval.
- Cost variance vs. budget ≤ 10%.

## Rollout

1. **Foundation.** Codename, SRE memory, ops dashboard skeleton per project.
2. **Observability defaults** seeded at project creation.
3. **Incident lifecycle UI.**
4. **Cost watch unified** (AI + infra).
5. **Backup drills + secret rotation.**
