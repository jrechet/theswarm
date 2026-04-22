# TechLead — Next

> Each TechLead instance on a project has a codename (e.g., `Marcus`, `Leila`, `Ivan`) persisted in memory and shown throughout the UI.

## Today

- Two entry points: `breakdown` (splits ready user-stories into dev sub-tasks) and `review_loop` (polls PRs, reviews with Claude, approves/merges).
- StateGraph in `src/theswarm/agents/techlead.py`. Review JSON schema (`decision`, `severity`, `override_reason`).
- Pragmatic override: REQUEST_CHANGES downgraded to APPROVE when no critical issues — good default, but currently invisible and not calibrated per project.

## Gaps

- **No architectural memory.** Re-derives the "shape" of the codebase every review; doesn't remember past refactors, ADRs, or the debt register.
- **No tech watch.** Doesn't know when a dependency has a CVE, when a major version drops, when a faster alternative lands, or when the framework recommends a new pattern.
- **Review quality drifts.** No calibration loop — reviewers don't learn which past calls were right/wrong.
- **Breakdown is ad-hoc.** No estimation, no dependency graph, no risk tagging.
- **No second opinion.** Solo reviewer on its own PRs (merging own work pattern via Dev).
- **No repo hygiene duties.** Doesn't clean up stale branches, stale labels, abandoned draft PRs.

## Next responsibilities

### 1. Architecture custodianship

- **ADR stream.** TechLead writes Architecture Decision Records for non-trivial choices (new dep, new module, schema change, API boundary). Stored in `docs/adr/NNNN-title.md`, linked from dashboard.
- **Codebase map.** Maintains a generated + curated map: module graph, dep graph, hotspots, owners. Regenerated nightly. Used to ground reviews ("this PR touches hotspot X, add extra tests").
- **Debt register.** Tracks known issues with severity, age, blast radius; proposes debt-payoff stories to PO.

### 2. Technology watch (Veille tech)

- **Dependency radar.** Daily: `osv-scanner` / `pip-audit` / `npm audit` / GitHub security advisories against the project's lockfile. Auto-opens `deps:security` issues for CVEs above chosen severity.
- **Version radar.** Weekly: check major/minor versions of top 20 deps, classify upgrade as `routine` / `breaking` / `new-capability`, propose upgrade stories.
- **Framework radar.** Subscribes to release feeds of the project's framework (e.g., FastAPI, React, Flutter, Django). Summarizes new features, deprecation warnings.
- **Pattern radar.** Weekly pass on curated sources (awesome-X, trending repos in the same topic, relevant newsletters). Extracts candidate patterns with examples; PO decides if they become stories.
- **Internal cross-project.** Reads `cross_project/patterns` memory; surfaces ideas proven on sibling projects.

### 3. Calibrated code review

- **Review playbook** per project: severity rubric, project-specific smells (e.g., "no direct SQL in API layer"), pragmatic overrides allowed.
- **Review calibration loop.** Every N cycles, run a retrospective comparing past review verdicts vs. bugs that shipped. Updates rubric + memory.
- **Second-opinion mode.** When touching critical modules (flagged in `critical_paths.yaml`), spawn a second reviewer sub-task (different temperature, or a different model, or an `architect` role).
- **Explain-the-review.** Reviews include a "why this matters" paragraph linked to ADRs / memory. Dashboard surfaces this so humans can learn or override.

### 4. Story breakdown with teeth

- **Dependency DAG.** Breakdown produces a graph; the Dev loop picks tasks respecting dependencies (no blocked work).
- **Size estimation.** Each task gets an estimate (XS / S / M / L / XL) with effort buckets calibrated from past cycles.
- **Risk tagging.** Tasks flagged `risk:high` trigger extra review, extra E2E, or get sent to a higher-capability model.
- **Definition of ready checklist.** Breakdown refuses stories missing acceptance criteria; bounces them back to PO with a precise reason.

### 5. Repository hygiene

- Auto-close stale draft PRs after N days of inactivity (with a polite comment).
- Prune stale branches; keep `main` clean.
- Enforce branch naming and commit-message conventions as a pre-merge check.
- Keep CODEOWNERS / issue templates up to date.

### 6. Mentor the Dev role

- When a Dev PR has a HIGH-severity finding, TechLead writes a short `learnings` memory entry that Dev will read on the next cycle.
- Periodic "tech review" brief: one-paragraph guidance on the most common class of issue caught this week.

## New tools

| Tool | Purpose |
|---|---|
| `osv-scanner` / `pip-audit` / `npm audit` | Dependency vulns |
| GitHub Security Advisories API | CVE feed |
| `semgrep --config=auto` (already partially used by QA) | Static patterns |
| `ast-grep` / tree-sitter | Codebase maps and hotspot detection |
| Release-feed aggregator | Framework watch |
| Lightweight ADR generator prompt | ADR creation |

## Memory patterns

- **Per-project-per-TechLead memory** `(project_id, codename)`:
  - `architecture` — stable design invariants, boundaries, module ownership.
  - `adrs` — index of ADRs with summaries.
  - `debt` — debt entries with severity + age.
  - `review_calibration` — past verdicts vs. outcomes.
  - `dep_radar` — dependency state + last check.
  - `critical_paths` — files/modules requiring extra scrutiny.
- Global promotions: cross-project patterns, reusable review heuristics.

## Dashboard surfaces

- **Tech radar** (like ThoughtWorks radar, auto-filled): adopt / trial / assess / hold.
- **ADR list** with search + diff view.
- **Dependency health** panel with CVE severities, age of lock, proposed upgrades.
- **Debt register** with owner, severity, age, blast radius.
- **Review insights** — trend of review severities, false-positive/negative rate vs. humans.

## Success metrics

- Median time to CVE triage ≤ 24h.
- ≥ 1 ADR per architectural change.
- Breakdown respects DAG 100% (no cycle-blocked tasks).
- Review calibration: < 10% of merged PRs followed by a rollback or hot-fix.
- Debt register drain rate ≥ production rate (net-reducing over time).

## Rollout

1. **Foundation.** Codename, per-project memory namespace, review playbook + severity rubric loaded into prompts.
2. **Breakdown v2.** DAG + estimation + risk tagging + definition-of-ready gate.
3. **Radars.** Dependency, framework, pattern radars with dashboard panels.
4. **ADRs & debt.** ADR generator, debt register, calibration loop.
5. **Second-opinion mode** for critical paths.
