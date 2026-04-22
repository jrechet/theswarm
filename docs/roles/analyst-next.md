# Analyst (Data / Analytics) — NEW role

> Codenamed (e.g., `Ravi`, `Noa`, `Emi`). Per project.

## Why this role

Outcome framing matters (see `po-next.md`). Saying "we improved sign-up" is only credible if someone measures it. Analyst closes the loop from _shipped story_ → _metric moved_.

## Responsibilities

### 1. Instrumentation plan

- For every user-visible story with a metric claim, Analyst writes a short plan: events to emit, properties, destination (PostHog / Mixpanel / Plausible / in-house), privacy notes.
- Dev implements; Analyst verifies events land correctly before ship.

### 2. Metric garden

- Per project: inventory of KPIs (activation, retention, reliability, business). Each with definition, owner, SLA on freshness.
- Analyst catches metric drift (name collisions, broken events).

### 3. Experimentation

- A/B + holdout support: Analyst defines variants, sample size, primary + guardrail metrics; Dev implements; Analyst reads the result.
- Explicit stop-rules (we don't peek).

### 4. Usage insights

- Weekly usage digest: top features used, cold features, top drop-off points.
- Funnel analyses on declared critical flows.
- Feeds PO inbox with signals ("feature X has 2% activation — kill or fix?").

### 5. Outcome verification

- Post-ship: 7/14/30 day check on each story's declared metric.
- Attaches the result to the demo report retroactively (`outcome_verified_at`).

### 6. Data hygiene

- Co-owns data retention with Security.
- PII redaction in events; no raw identifiers where a hash suffices.

## Interactions

- **← PO.** Story metric claims flow to Analyst.
- **→ Dev.** Instrumentation snippets.
- **→ QA.** Event-emission tests (verifies events fire).
- **→ PO.** Outcome results and usage signals.

## Memory patterns

- Per-project-per-Analyst: `metrics`, `events_schema`, `experiments`, `cohorts`, `funnel_baselines`.

## Dashboard surfaces

- **Metrics** page per project with KPI cards (sparkline, target, owner).
- **Experiments** log with status + results.
- **Outcome trails** linking stories → metrics → deltas.
- **Data quality** panel (broken events, missing props).

## New tools

| Tool | Purpose |
|---|---|
| PostHog / Plausible / Mixpanel SDKs | Event destinations |
| DuckDB / pandas | Local analytics |
| Embedded charts (e.g., uPlot) | Dashboard |

## Success metrics

- 100% of metric-claiming stories have an outcome verification within 30 days.
- Event schema drift detected within 24h.
- ≥ 1 actionable signal surfaced to PO per week.

## Rollout

1. **Foundation.** Codename, metrics inventory template, events schema file.
2. **Instrumentation plan per story.**
3. **Usage digests + outcome verification.**
4. **Experiment framework.**
5. **Data hygiene gates.**
