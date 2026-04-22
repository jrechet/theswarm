# Chief of Staff (Portfolio Manager) — NEW role

> Single instance, portfolio-scoped. Codename optional (often the same across all projects, e.g., `Ada`). Not a "chief" in the sense of overriding other roles — more like a conductor.

## Why this role

Once there are multiple projects and many agent codenames, someone must:

- Keep roster consistent (assignments, codenames, churn).
- Route human asks to the right agent on the right project.
- Surface cross-project signals the specialists individually miss.
- Run the weekly cadence across the swarm.
- Protect budgets at the portfolio level.

Without this role, the human operator (you) becomes the conductor. That's fine at 1–2 projects and doesn't scale.

## Responsibilities

### 1. Roster

- Maintains the registry of `(project, role, codename)`. Creates assignments on project creation. Handles codename uniqueness.
- Removes assignments on project archive; archives their memory (retained but frozen).

### 2. Routing

- Central chat entry point: `@Ada` (Chief of Staff) in Mattermost or dashboard. Routes to the right specialist based on content, escalates when unclear.
- Maintains a per-user preference (e.g., "@user prefers DMs on Mattermost; weekly digest via email").

### 3. Portfolio cadence

- Monday: plan-the-week brief across all projects.
- Friday: outcomes digest.
- Daily: one-line status ("3 cycles ran overnight, 2 merged, 1 needs your attention").
- Quarterly: portfolio review with Architect + POs.

### 4. Budget & attention governance

- Portfolio budgets (AI spend + infra + human attention).
- Fair-share scheduler: no single project starves others of cycles.
- Flags projects that haven't shipped in N days ("is this still alive?").

### 5. Cross-project signals

- Notices patterns across POs' inboxes ("three projects flagged logging gaps this week") and surfaces to Architect.
- Triggers cross-project refactor programs (partners with Architect).

### 6. Onboarding / offboarding projects

- Owns the new-project wizard: creates roster, assigns codenames, seeds memory from a template, confirms config with the human operator.
- Archival: freeze memory, export, remove from active dashboards.

### 7. Human-in-the-loop mediation

- Collects human corrections (e.g., "that proposal was off-base, don't do that again") and routes them to the right agent's memory with a tag.

## Interactions

- **Central.** Touches all roles lightly; owns none of their decisions.
- **Never** overrides a role's call in-flow — collects signal and surfaces next cycle.

## Memory patterns

- Portfolio-scoped: `roster`, `cadence`, `budgets`, `human_preferences`, `escalations`, `archive_index`.

## Dashboard surfaces

- **Home** (replaces / augments today's dashboard home):
  - Portfolio heartbeat (projects, cycles today, cost today, alerts).
  - Human inbox (asks routed to you).
  - Team roster view (all codenames across projects).
- **Routing rules** editor.
- **Weekly / daily digest** configurator.
- **Budget controls** portfolio-wide.
- **Onboarding wizard** for new projects.

## New tools

| Tool | Purpose |
|---|---|
| Existing EventBus / SSE | Aggregates portfolio events |
| Existing CronScheduler | Digests |
| `AskUserQuestion` tool pattern | Structured asks to human |

## Success metrics

- Routing accuracy ≥ 90% (asks land on the right agent first try).
- Digest open + action rate.
- Project starvation events = 0.
- Roster integrity: unique codenames, no orphaned memory.

## Rollout

1. **Foundation.** Roster registry, codename assignment, Chief-of-Staff memory.
2. **Central chat entry + routing.**
3. **Daily + weekly cadences.**
4. **Budget governance.**
5. **Onboarding wizard + archive flow.**
