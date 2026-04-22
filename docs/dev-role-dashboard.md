# Dev Plan — Roles, Memory, and a Dashboard-Centric Swarm

**Scope.** Evolve TheSwarm from a 4-role daily cycle into a multi-project, multi-role studio where:

- The **dashboard is the control surface** — you manage roster, projects, cycles, memory, budgets, and you _talk_ to agents from it.
- Agents have **codename identities** (human first names) unique per `(project, role)` assignment.
- Memory is keyed at three layers: **role**, **project**, and the critical intersection **role × project** (with a global / portfolio layer above).
- New roles (Scout, Designer, SRE, Security, Analyst, Writer, Release, Architect, Chief of Staff) slot in without breaking the current PO/TechLead/Dev/QA pipeline.
- Everything existing (LangGraph, SQLite repos, EventBus, SSE, CronScheduler, autonomous mode) is **extended, not rewritten**.

> See per-role briefs:
> [po-next](roles/po-next.md) · [techlead-next](roles/techlead-next.md) · [dev-next](roles/dev-next.md) · [qa-next](roles/qa-next.md) ·
> [scout-next](roles/scout-next.md) · [designer-next](roles/designer-next.md) · [sre-next](roles/sre-next.md) · [security-next](roles/security-next.md) · [analyst-next](roles/analyst-next.md) · [writer-next](roles/writer-next.md) · [release-next](roles/release-next.md) · [architect-next](roles/architect-next.md) · [chief-of-staff-next](roles/chief-of-staff-next.md)

---

## 0. Progress tracker

| Phase | Scope | Status |
|---|---|---|
| A | Identity & memory foundation | ✅ Done |
| B | Dashboard chat + human-in-the-loop | ✅ Done |
| C | PO intelligence | ✅ Done |
| D | TechLead tech-watch + review rigor | ✅ Done |
| E | Dev rigour | ✅ Done |
| F | QA enrichments | ✅ Done |
| G | Scout (new role) | ✅ Done |
| H | Designer (new role) | ✅ Done |
| I | Security + SRE (new roles) | ✅ Done |
| J | Analyst + Writer + Release (new roles) | ✅ Done |
| K | Architect + Chief of Staff | ✅ Done |
| L | Polish & portfolio | ✅ Done |

---

## 1. Guiding principles

1. **Dashboard-first.** No new feature lands without a dashboard surface. If a human can't see it or act on it, it doesn't exist.
2. **Codenames are identity, not decoration.** Memory, logs, dashboard events, and chat all use the codename.
3. **Memory is three-layered.** `global`, `project`, `role×project`. Promotion is explicit and auditable.
4. **Specialisation over generalism.** Each role has a narrow lane with clear entry and exit points.
5. **Human-in-the-loop, not human-on-critical-path.** Humans should be able to nudge, block, redirect — but the swarm runs without them.
6. **Extend, don't rewrite.** Keep LangGraph, keep the Clean Architecture layering, keep SQLite.

---

## 2. Codename / identity system

### 2.1 Registry

New SQLite table:

```sql
CREATE TABLE role_assignments (
  id TEXT PRIMARY KEY,                -- uuid
  project_id TEXT NOT NULL,
  role TEXT NOT NULL,                 -- po | techlead | dev | qa | scout | designer | sre | security | analyst | writer | release | architect | chief_of_staff
  codename TEXT NOT NULL,             -- unique across (role, codename) portfolio-wide, and human-readable
  assigned_at DATETIME NOT NULL,
  retired_at DATETIME NULL,
  config_json TEXT NOT NULL DEFAULT '{}',    -- per-assignment tweaks (tone, model, budgets)
  UNIQUE (codename),
  UNIQUE (project_id, role, assigned_at)
);
CREATE INDEX idx_role_assignments_project ON role_assignments(project_id);
CREATE INDEX idx_role_assignments_role ON role_assignments(role);
```

### 2.2 Codename pool

- `data/codenames.yaml` — large curated list of short, easy-to-pronounce first names across cultures (Alice, Priya, Kenji, Tariq, Yara, Ada, Otis, Freya, ...).
- On assignment, pick first unused codename deterministically (hash of `project_id + role + pool_index`) for reproducibility, or let the user pick from UI.
- Retired codenames released after 90 days (memory retained under the retired codename; history preserved).

### 2.3 Display rules

- All UI, logs, SSE events, chat replies use `codename (role)` — e.g., `Alice (PO)`.
- Memory entries already carry an `agent` field; migrate to `codename` with a `role` sibling field for filtering.
- Retrospectives and improvement suggestions likewise carry codename.

---

## 3. Memory architecture

### 3.1 Three layers

| Layer | Scope | Example |
|---|---|---|
| **Global** | All projects, all agents | "Users reject auto-push by default" |
| **Project** | One project, any agent on it | "This repo uses FastAPI + HTMX + SQLite" |
| **Role × Project** | One codename on one project | "Alice (PO) decided to defer mobile until Q3" |

Existing schema (`memory_entries` with `project_id`, `agent`, `category`) already supports this — we only need:

- Rename/extend `agent` to the codename; add a `role` column.
- Add a `scope` column (`global` / `project` / `role_project`) to make promotion explicit.
- Index `(project_id, role, codename, category)`.

### 3.2 Categories (extended)

Keep current (`stack`, `conventions`, `errors`, `architecture`, `improvements`, `cross_project`) and add:

- `competitors`, `policy`, `okr`, `signals`, `decisions` (PO)
- `adrs`, `debt`, `dep_radar`, `critical_paths`, `review_calibration` (TechLead)
- `test_patterns`, `flakes`, `gaps`, `perf_baselines`, `a11y_violations` (QA)
- `tokens`, `components`, `references` (Designer)
- `runbooks`, `incidents`, `alerts`, `slos`, `infra_costs` (SRE)
- `threat_model`, `findings`, `authz`, `crypto_inventory` (Security)
- `metrics`, `events_schema`, `experiments`, `cohorts` (Analyst)
- `style_guide`, `docs_map`, `tutorial_index` (Writer)
- `versions`, `rollouts`, `flags`, `rollbacks` (Release)
- `paved_road`, `portfolio_adrs`, `direction_briefs` (Architect, scope=global)
- `roster`, `cadence`, `budgets`, `human_preferences`, `escalations` (Chief of Staff, scope=global)

### 3.3 Promotion

- `promote_to_global(entry, rationale)` already exists as a concept in `domain/memory`. Wire it into the dashboard (button: **Promote**). Logged in `project_audit`.
- Demotions are rare but allowed (mistake correction).

### 3.4 Retrieval

- Keep role-filtered recall (`ROLE_CATEGORIES`), extend per new role.
- Add **semantic recall** (optional, behind a flag): embeddings on entries, top-k by similarity to the current task. Stored in SQLite via `sqlite-vec` extension to keep zero extra infra.

### 3.5 Prompts

- Replace hardcoded inline prompts in `src/theswarm/agents/*.py` with a template per role under `src/theswarm/agents/prompts/<role>/<node>.md`.
- Each template receives: `codename`, `project_meta`, `memory_snippet`, task-specific inputs.
- Dashboard exposes a **Prompt library** page (read-only to start; editable later with an audit trail).

---

## 4. Dashboard rework (THE central surface)

### 4.1 Information architecture

```
/                           Portfolio home (Chief of Staff view)
/projects                   List
/projects/{id}              Project home (overview + tabs)
  ├── tab: Overview         Active cycle, KPIs, recent events
  ├── tab: Team             Roster (codenames), memory per role × project
  ├── tab: Backlog          PO inbox, proposals, stories
  ├── tab: Cycles           List + detail + replay
  ├── tab: Demos            (existing) demo player + compare
  ├── tab: Reports          (existing)
  ├── tab: Tech Radar       TechLead + Scout feeds filtered to this project
  ├── tab: Quality          QA dashboards (flake, perf, a11y, coverage)
  ├── tab: Security         Findings, SBOM, threat model
  ├── tab: Ops              SRE dashboards (incidents, deploys, cost)
  ├── tab: Metrics          Analyst KPIs
  ├── tab: Docs             Writer health
  ├── tab: Releases         Release Manager calendar + flags
  ├── tab: Design           Designer system + briefs
  ├── tab: Memory           Three-layer memory browser (with filters and promotion)
  ├── tab: Settings         Config, schedule, budgets, integrations

/team                       Portfolio roster (all codenames)
/intel                      Scout feed (portfolio)
/portfolio/adrs             Architect ADRs
/budgets                    Portfolio budgets
/chat                       Unified chat (threaded; routes to codenames)
/history                    Replay archive
```

Tabs can be lazy-rendered (HTMX fragment endpoints already in use).

### 4.2 Chat as a first-class surface

Currently persona-via-Mattermost. Add a dashboard-native chat:

- **Thread per `(project, codename)`** — pinned on the project home.
- **Global Chief-of-Staff thread** on `/chat`.
- Messages routed to the right agent via the existing NLU + a routing table by codename.
- Outgoing messages from agents use their codename and avatar (deterministic color + initials).
- SSE streams typing / partial replies.
- Asks that require human confirmation use an `AskUserQuestion`-style inline card.

### 4.3 PO-oriented "talk-to-me" flows

From anywhere on the dashboard, the user can:

- **`@Alice (PO)` — "ship a story that X"** → creates a proposal in the backlog.
- **`@Marcus (TechLead)` — "upgrade dep Y to Z"** → breaks down into an upgrade task next cycle.
- **`@Ada (Chief of Staff)` — "what's hot this week?"** → digest with action buttons.

### 4.4 Live cycle view (already exists) enriched

- **Agent status lane per codename** with state chip (idle / thinking / acting / waiting-on-human / blocked).
- **Nudge button** per running step (feeds into agent memory before next tick).
- **Intervene** (pause / skip / override) with audit entry.

### 4.5 Memory browser

- Tree: `global → project → role×project`.
- Filters: category, codename, date, confidence, scope.
- Actions: edit (human), promote, demote, archive, export.
- Audit log of every edit.

### 4.6 Onboarding wizard

- Create project → choose framework → pick roles → auto-assign codenames (or let human pick) → seed memory from the paved-road template → confirm schedule + budgets → run a first cycle.
- Entire flow takes < 2 minutes.

### 4.7 Roster / team page

- Portfolio card grid of all codenames with: role badge, project, last active, open asks, memory size, recent wins.
- Actions: retire / reassign / rename (keeps memory trail).

---

## 5. Agent orchestration changes

### 5.1 Cycle types

Today: one daily cycle (morning / dev / demo / evening). Extend:

- `dev-cycle` (current).
- `intel-cycle` — Scout-only, runs frequently.
- `infra-cycle` — SRE-led, ships infra changes, no app code.
- `release-cycle` — Release Manager-led, cuts and ships a version.
- `research-cycle` — Architect-led, produces direction briefs.

Cycle type is a field on the `cycles` table; dashboards filter accordingly.

### 5.2 Gating graph

The pipeline gets gates (a gate is a specialist check that can block):

```
PO → TechLead → Dev → (Designer gate if UI) → QA → (Security gate if authZ/PII)
                                            ↓
                                       Release gate → ship
```

Gates are declared per story (labels / config) rather than hardcoded. The cycle orchestrator is a DAG, not a straight line.

### 5.3 Autonomy spectrum per role

Per-project, per-role config:

| Level | Meaning |
|---|---|
| `suggest` | Agent proposes; human approves every step |
| `act-with-confirm` | Agent acts on reversible things; pauses for irreversible |
| `act-auto` | Agent acts autonomously; humans can intervene post-hoc |

Defaults are sensible: PO=`act-with-confirm`, Dev=`act-auto`, Security=`act-with-confirm`, Release=`act-with-confirm`, Scout=`suggest`.

### 5.4 Event model (extended)

Domain events gain `codename`, `role`, `project_id`. EventBus + SSE unchanged. New events: `PromotionProposed`, `MemoryEdited`, `GateBlocked`, `HumanNudgeApplied`, `AgentAskedHuman`, `AskAnswered`.

---

## 6. Implementation phases

Each phase is a mergeable slice. Estimates assume solo operator + TheSwarm dogfooding itself.

### Phase A — Identity & memory foundation (~2 cycles) ✅ **DONE**

**Goal:** codenames everywhere, three-layer memory, no new roles yet.

- [x] `role_assignments` table + migration + domain entity `RoleAssignment`.
- [x] Codename pool (`data/codenames.yaml`) + deterministic picker (`infrastructure/agents/codename_pool.py`).
- [x] Migrate `memory_entries.agent` → `codename` + new `role` + `scope_layer` columns (migration v006).
- [x] Update `load_context()` to inject persona preamble with codename + role + project.
- [x] CLI: `projects add` auto-assigns the 4 existing roles (PO, TechLead, Dev, QA) with codenames via `RoleAssignmentService`.
- [x] Dashboard: **Team** tab on project (HTMX fragment), **Roster** global page at `/team`.
- [x] All agent prompts carry codename and project meta (threaded through `AgentState.codenames`).
- [x] Tests: 100% domain coverage on new modules; 1400 tests passing (75+ new).

### Phase B — Dashboard chat + human-in-the-loop (~2 cycles) ✅ **DONE**

- [x] Unified chat service (dashboard-native) with threads per `(project, codename)` (`application/services/chat_service.py`).
- [x] NLU routing with codename-aware addressing (`@Alice` → resolved role for project X). `RuleBasedNLU` fallback + pluggable `NLUPort`.
- [x] SSE streaming at `/chat/{thread_id}/stream` (poll-based, minimal overhead).
- [x] Nudge endpoint `/cycles/{id}/nudge` + pause/intervene endpoints write to `hitl_audit` table.
- [x] HITL audit viewer at `/hitl` and `/projects/{id}/hitl`.
- [x] Audit of every human intervention (`SQLiteHITLAuditRepository`).
- [x] Chat index `/chat`, thread page `/chat/{thread_id}`, project chat fragment on project detail.
- [x] Tests: 37 new (domain, repo, service, routes).

### Phase C — PO intelligence (~2 cycles) ✅ **DONE**

- [x] Competitor + ecosystem watch jobs (`application/services/watch_jobs.py` + `infrastructure/scheduling/periodic_runner.py`; pluggable `SignalSource` callables; THREAT/OPPORTUNITY bypass confidence floor).
- [x] Proposals inbox (`/projects/{id}/proposals` and portfolio-wide `/proposals`) with Approve / Reject / Defer / Ask; dedup-aware upsert preserves prior human decisions.
- [x] OKR editor (`/projects/{id}/okrs`) with objective + quarter + owner + key results; key-result progress tracked.
- [x] Weekly digest generator (`application/services/insight_digest.py`) — rule-based aggregation over 7-day signals + recent proposals, rendered at `/projects/{id}/digest`.
- [x] Policy file per project (`/projects/{id}/policy`) with banned terms + require-review terms as hard filter in `PolicyFilter.evaluate()` (BLOCK / REVIEW / ALLOW).
- [x] Migration v008 + SQLite repos (`product_proposals`, `product_okrs`, `product_key_results`, `product_policies`, `product_signals`, `product_digests`).
- [x] Tests: 69 new (16 domain + 17 infra + 24 application + 4 periodic-runner + 14 presentation/routes); 1512 total passing.

### Phase D — TechLead tech-watch + review rigor (~2 cycles) ✅ **DONE**

- [x] Dependency radar job (`application/services/dependency_radar.py` with pluggable `DepScanner` callables mirroring Phase C `watch_jobs`; `SQLiteDepFindingRepository.upsert` dedupes by `(project_id, package, advisory_id)` via UNIQUE index; severity levels INFO→CRITICAL from `domain/techlead/value_objects.py`).
- [x] ADR generator + ADR browser UI (`ADRService.propose/accept/reject/supersede`; per-project auto-assigned `number` via `MAX(number)+1`; `/projects/{id}/adrs` fragment + `/projects/{id}/adrs/{adr_id}` detail page; slug derived from title; supersedes link maintained bidirectionally).
- [x] Debt register UI (`DebtService.add/resolve`; `/projects/{id}/debt` fragment with severity-ordered list + blast-radius + age days; `DebtEntry.age_days` computed from `created_at`/`resolved_at`).
- [x] Review calibration loop (`ReviewCalibrationService.record/set_outcome/stats`; FP rate = `REQUEST_CHANGES+CLEAN+override` / requested, FN rate = `APPROVE+(PATCH_NEEDED|REVERTED)` / approved; `/projects/{id}/reviews/calibration` fragment).
- [x] Second-opinion reviewer for critical paths (`SecondOpinionService` + `CriticalPath.matches()` using `fnmatch` glob / substring fallback; `/projects/{id}/critical-paths` fragment with add/delete).
- [x] Migration v009 + SQLite repos (`techlead_adrs`, `techlead_debt`, `techlead_dep_findings`, `techlead_review_verdicts`, `techlead_critical_paths`).
- [x] Tests: 56 new (15 domain + 14 infra + 14 application + 13 presentation/routes); 1568 total passing.

### Phase E — Dev rigour (~1 cycle) ✅ **DONE**

- [x] Research-before-code step — `DevThought` stream (`domain/dev_rigour/entities.py`) with `ThoughtKind.EXPLORE/REUSE/LIBRARY/PLAN/NOTE`; `DevThoughtService.log/recent/for_task`; `/projects/{id}/dev/thoughts` fragment with live form + severity-coded list.
- [x] TDD gate — `TddArtifact` with RED→GREEN→REFACTOR state machine (`is_green` property); `TddGateService.record_red/record_green/mark_refactor` upserts by `(project_id, task_id)`; `/projects/{id}/dev/tdd` fragment lets users promote RED to GREEN inline.
- [x] Refactor preflight on large deletions — `RefactorPreflight` entity + `RefactorPreflightService.evaluate` with configurable `threshold_lines` (default 20); diffs under threshold short-circuit to None; `/projects/{id}/dev/preflight` fragment shows proceed/bail decisions with callers checked.
- [x] Self-review prompt before PR — `SelfReview` with `SelfReviewFinding` tuples (severity/category/message/waived/waive_reason); `high_count` excludes waived HIGH/CRITICAL; `SelfReviewService.make_finding`; `/projects/{id}/dev/self-reviews` fragment lists findings with severity borders and waived-strikethrough styling.
- [x] Coverage delta on PRs — `CoverageDelta` entity with `total_before_pct/total_after_pct/changed_lines_pct/threshold_pct`; `delta` and `passes_threshold` properties; `CoverageDeltaService.record/latest_for_pr`; `/projects/{id}/dev/coverage` fragment shows pass/fail with deltas.
- [x] Migration v010 + SQLite repos (`dev_thoughts`, `tdd_artifacts` with UNIQUE `(project_id, task_id)`, `dev_refactor_preflights`, `dev_self_reviews`, `dev_coverage_deltas`).
- [x] Tests: 60 new (24 domain + 8 infra + 15 application + 13 presentation/routes); 1628 total passing.

### Phase F — QA enrichments (~2 cycles) ✅ **DONE**

- [x] Archetype mix per story — `TestPlan` entity with `required/produced` tuples of `TestArchetype.UNIT/INTEGRATION/E2E/VISUAL/A11Y/PERF/SECURITY`; `coverage_ratio` + `missing` properties; `ArchetypeMixService.set_required/mark_produced` upserts by `(project_id, task_id)`; `/projects/{id}/qa/plans` fragment lists plans with archetype badges (green=produced, amber=missing) and inline "mark produced" form.
- [x] Flake retry + quarantine + flake-score panel — `FlakeRecord` with `flake_score` (failures/runs, clamped 0–1) and `should_quarantine(threshold=0.2, min_runs=5)`; `FlakeTrackerService.record_run` accumulates per-test counters; `QuarantineService.quarantine/release` with `QuarantineEntry.status` state machine; `/projects/{id}/qa/flakes` scoreboard (hot-border on quarantine threshold) and `/projects/{id}/qa/quarantine` fragment with active/released sections.
- [x] Quality gates — `QualityGate` entity with `GateName.AXE/LIGHTHOUSE/K6/GITLEAKS/OSV/SBOM/LICENSE` and `GateStatus.PASS/FAIL/WARN/SKIPPED/UNKNOWN`; `is_blocking` only true on FAIL; `QualityGateService.record/latest_snapshot` returns freshest gate per name; `/projects/{id}/qa/gates` fragment shows one card per gate with status-colored border and "never run" empty state.
- [x] Richer demo artifacts — `OutcomeCard` with `StoryAcceptance` tuples (text/passed/evidence), `metric_name/before/after`, `screenshot_path`, `narrated_video_path`; `pass_count/fail_count/all_passed` properties (empty acceptance is not passing); `OutcomeCardService.create/list` with `make_acceptance` factory; `/projects/{id}/qa/outcomes` fragment shows checklist with before→after metric deltas.
- [x] Migration v011 + SQLite repos (`qa_test_plans` with UNIQUE `(project_id, task_id)`, `qa_flake_records` with UNIQUE `(project_id, test_id)`, `qa_quarantine`, `qa_quality_gates`, `qa_outcome_cards`).
- [x] Tests: 57 new (23 domain + 9 infra + 11 application + 14 presentation/routes); 1685 total passing.

### Phase G — Scout (new role) (~2 cycles) ✅ Done

- [x] Scout domain model (`IntelSource`, `IntelItem`, `IntelCluster` frozen dataclasses with `hash_url` normalization for dedup; signal_rate/is_healthy/is_actionable properties) + value objects (`IntelCategory`, `IntelUrgency`, `SourceKind`).
- [x] Migration v012 + SQLite repos (`intel_sources`, `intel_items` with UNIQUE `url_hash`, `intel_clusters`). `IntelItem.add` catches IntegrityError on url_hash collision and returns None for silent dedup.
- [x] Application services: `IntelSourceService` (register/record_success/record_error health tracking), `IntelFeedService` (ingest/classify/mark_action + filter-by-category/project feed), `IntelClusterService` (create with members, idempotent add_member).
- [x] Dashboard routes + HTMX fragments: `/intel/feed` + `/projects/{pid}/intel/feed` (category/urgency badges, action form), `/intel/sources` (signal-rate health gauge), `/intel/clusters` (grouped stories). Portfolio ingest form + per-project read-only feed. CSS: category colour-coded left borders (threat/cve=red, opportunity=green, framework/paper=blue, noise=dim) + urgency inset shadow.
- [x] Dashboard slots: portfolio intel feed/sources/clusters on main dashboard; per-project intel feed + sources on project detail page.
- [x] Tests: 47 new (19 domain + 8 infra + 10 application + 10 presentation/routes); 1732 total passing.

### Phase H — Designer (new role) (~2 cycles) ✅ Done

- [x] Domain: 5 entities (`DesignToken`, `ComponentEntry`, `DesignBrief`, `VisualRegression`, `AntiTemplateCheck`) + 4 enums (`TokenKind`, `ComponentStatus`, `BriefStatus`, `CheckStatus`) with computed properties: `is_shared`/`is_retired`, `is_approved`/`blocks_dev` (DRAFT + CHANGES_REQUESTED gate Dev), `is_blocking` (FAIL-only on visual regression), `passes_bar` (≥4 qualities AND 0 violations).
- [x] Migration v013: 5 SQLite tables (`design_tokens`, `design_components`, `design_briefs`, `visual_regressions`, `anti_template_checks`) with UNIQUE (project_id+name) / (project_id+story_id) indexes, tuple round-trip via JSON columns.
- [x] Application services: `DesignSystemService` (upsert tokens preserving id+created_at), `ComponentInventoryService` (register/promote/deprecate + usage clamp), `DesignBriefService` (draft/mark_ready/approve/request_changes state machine), `VisualRegressionService` (capture + review), `AntiTemplateService.record` auto-derives status (violations→FAIL, ≥4 qualities→PASS, else WARN).
- [x] Dashboard routes + HTMX fragments: `/projects/{pid}/design/tokens|components|briefs|visual-regressions|anti-template` with inline review/promote/deprecate forms. CSS: status-coloured left borders (approved=green, changes_requested=red, draft=grey, shared=green, deprecated=red) + new badge colours (`badge-approved`, `badge-changes_requested`, `badge-shared`, `badge-deprecated`).
- [x] Dashboard slots: 5 per-project slots on project detail page (tokens, components, briefs, visual regressions, anti-template).
- [x] Tests: 42 new (7 domain + 8 infra + 12 application + 15 presentation/routes); 1774 total passing.

### Phase I — Security + SRE (new roles) (~3 cycles) ✅ Done

- [x] Domain — Security: 5 frozen entities (`ThreatModel` with `freshness_days`/`is_stale`, `DataInventoryEntry` with `is_sensitive`, `SecurityFinding` with per-severity SLA deadline + `is_breaching_sla`, `SBOMArtifact`, `AuthZRule` with composite `key`) + 4 enums (`DataClass`, `FindingSeverity`, `FindingStatus`, `AuthZEffect`). SLA policy: critical 24h, high 7d, medium 30d, low/info 90d.
- [x] Domain — SRE: 3 frozen entities (`Deployment` with `is_terminal`/`duration_seconds`, `Incident` with `timeline: tuple[str, ...]` + `mttr_seconds`/`mttm_seconds`, `CostSample`) + 4 enums (`DeployStatus`, `IncidentSeverity` sev1-4, `IncidentStatus` open→triaged→mitigated→resolved→postmortem_done, `CostSource` ai/infra/saas/other).
- [x] Migrations v014 + v015: 8 SQLite tables (threat_models UNIQUE project_id, data_inventory UNIQUE project_id+field_name, security_findings, sbom_artifacts, authz_rules UNIQUE project_id+actor_role+resource+action, deployments, incidents with timeline_json, cost_samples).
- [x] Application services: 5 Security (`ThreatModelService`, `DataInventoryService`, `SecurityFindingService` open/triage/resolve/suppress, `SBOMService.latest`, `AuthZService` upsert/delete) + 3 SRE (`DeploymentService` start/succeed/fail/rollback, `IncidentService` with auto-timestamped timeline + full 5-stage lifecycle, `CostService.rollup` via SQL GROUP BY).
- [x] Dashboard routes + HTMX fragments: Security (`/projects/{pid}/security/threat-model|data-inventory|findings|sbom|authz` + triage/resolve sub-endpoints) + SRE (`/projects/{pid}/sre/deployments|incidents|cost` with lifecycle sub-endpoints for deploy succeed/fail/rollback and incident triage/mitigate/resolve/postmortem/timeline). CSS: severity-coloured left borders (critical/sev1=red, high/sev2=amber, medium/sev3=blue, low/sev4=grey), status-coloured deploy borders, badges for all severity/status/effect tiers.
- [x] Dashboard slots: 8 per-project slots on project detail page (5 Security + 3 SRE, grouped).
- [x] Tests: 63 new (18 domain + 10 infra + 13 application + 22 presentation/routes); **1837 total passing**.

### Phase J — Analyst + Writer + Release (new roles) (~3 cycles) ✅ Done

- [x] Domain — Analyst: 3 frozen entities (`MetricDefinition`, `InstrumentationPlan` with `is_blocking_outcome` true when MISSING, `OutcomeObservation` with `is_positive` true when IMPROVED) + 3 enums (`MetricKind` counter/gauge/histogram/ratio/currency, `InstrumentationStatus` proposed→implemented→verified / missing, `OutcomeDirection` improved/unchanged/regressed/inconclusive).
- [x] Domain — Writer: 3 frozen entities (`DocArtifact` with `needs_refresh` when STALE, `QuickstartCheck` with `is_broken` when FAIL, `ChangelogEntry` with `is_breaking` when BREAKING) + 4 enums (`DocKind` readme/quickstart/changelog/guide/api, `DocStatus` draft/ready/stale, `QuickstartOutcome` pass/fail/skipped, `ChangeKind` feat/fix/refactor/perf/docs/chore/breaking).
- [x] Domain — Release: 3 frozen entities (`ReleaseVersion` with `is_live` when RELEASED, `FeatureFlag` with `is_cleanup_overdue` when age > cleanup window, `RollbackAction` with `is_armed` when READY+ref) + 3 enums (`ReleaseStatus` draft/released/rolled_back, `FlagState` active/stale/archived, `RollbackStatus` ready/executed/obsolete).
- [x] Migrations v016 + v017 + v018: 9 SQLite tables (metric_definitions UNIQUE project_id+name, instrumentation_plans UNIQUE project_id+story_id+metric_name, outcome_observations append-only; doc_artifacts UNIQUE project_id+path, quickstart_checks append-only, changelog_entries append-only with version index; release_versions UNIQUE project_id+version, feature_flags UNIQUE project_id+name, rollback_actions with status field).
- [x] Application services: 3 Analyst (`MetricDefinitionService`, `InstrumentationPlanService` upsert+mark_status with missing_only filter, `OutcomeObservationService.record`) + 3 Writer (`DocArtifactService` upsert+mark_status with auto last_reviewed_at on READY, `QuickstartCheckService.record`, `ChangelogService` record+list_for_version+list_unreleased) + 3 Release (`ReleaseVersionService` draft→released→rolled_back with auto-timestamped released_at, `FeatureFlagService` upsert with 0..100 rollout clamp + archive, `RollbackActionService` arm/execute/mark_obsolete).
- [x] Dashboard routes + HTMX fragments: Analyst (`/projects/{pid}/analyst/metrics|instrumentation|outcomes` + `/instrumentation/{story_id}/{metric_name}/status`) + Writer (`/projects/{pid}/writer/docs|quickstart|changelog` + `/docs/status`) + Release (`/projects/{pid}/release/versions|flags|rollbacks` + lifecycle sub-endpoints for release, rollback, archive, execute, obsolete). CSS: kind-coloured metric borders, status-coloured plan/doc/release borders (missing=red, stale=amber, breaking=red, rolled_back=red), change-kind badges, flag cleanup-overdue warning, rollback armed flag.
- [x] Dashboard slots: 9 per-project slots on project detail page (3 Analyst + 3 Writer + 3 Release, grouped).
- [x] Tests: 80 new (Analyst 23 + Writer 26 + Release 31) — domain entities, SQLite repos, application services (upsert idempotency, lifecycle transitions, value errors for missing keys, rollout clamping), presentation routes (empty states, unknown enum fallback, 400 on bad status, 404 on missing resources, full CRUD flows); **1917 total passing**.

### Phase K — Architect + Chief of Staff (~2 cycles) ✅ Done

**Architect — ✅ Done**

- [x] Domain — Architect: 3 frozen entities (`PavedRoadRule` with `is_blocking` when REQUIRED, `PortfolioADR` with `is_portfolio_wide` when project_id="" and `is_active` when ACCEPTED, `DirectionBrief` with `is_project_scoped` when PROJECT) + 3 enums (`RuleSeverity` advisory/required, `ADRStatus` proposed/accepted/superseded/rejected, `BriefScope` portfolio/project).
- [x] Migration v019: 3 SQLite tables (paved_road_rules UNIQUE name, portfolio_adrs with supersedes column + project_id index, direction_briefs with focus_areas_text/risks_text newline-delimited + scope and project_id indexes).
- [x] Application services: `PavedRoadService` (upsert preserving id, list_all), `PortfolioADRService` (propose, accept, reject, supersede — all raise ValueError on missing), `DirectionBriefService` (record with project_id auto-cleared when scope != PROJECT, list_portfolio, list_for_project).
- [x] Dashboard routes + HTMX fragments: dual endpoints — portfolio-wide at `/architect/paved-road|adrs|briefs` and project-scoped at `/projects/{pid}/architect/adrs|briefs`; accept/reject POST handlers route back to the correct fragment view based on `adr.project_id`. CSS: severity-coloured rule borders (required=red with background tint, advisory=blue), ADR status-coloured borders (proposed=amber, accepted=green, rejected=grey, superseded=faded), brief scope-coloured borders, risks list in warning colour, narrative block with subtle background.
- [x] Dashboard slots: portfolio-wide Architect surfaces (paved-road, ADRs, briefs) remain at `/architect/*`; project detail page adds 2 per-project slots (ADRs — showing portfolio-wide ADRs alongside project-scoped ones, and project-scoped direction briefs).
- [x] Tests: 32 new (domain 8 + infra 4 + services 8 + routes 12) — entity invariants, SQLite UPSERT idempotency and supersedes handling, service-level ValueError on missing keys, portfolio-vs-project listing semantics (ADRs with `project_id=''` visible in per-project view), route-level enum fallback, 404 on missing ADR, dual-scope POST/GET paths; **1949 total passing**.

**Chief of Staff — ✅ Done**

- [x] Domain — Chief of Staff: 4 frozen entities (`RoutingRule` with `is_enabled` when ACTIVE, `BudgetPolicy` with `is_portfolio_wide` when project_id="" and `blocks_cycles` when EXCEEDED or PAUSED, `OnboardingStep` with `is_done` when COMPLETE or SKIPPED, `ArchivedProject` with append-only `archived_at` + `memory_frozen` flag) + 4 enums (`RuleStatus` active/disabled, `BudgetState` active/exceeded/paused, `OnboardingStatus` pending/complete/skipped, `ArchiveReason` shipped/abandoned/merged/other).
- [x] Migration v020: 4 SQLite tables (routing_rules UNIQUE pattern + status/priority indexes, budget_policies UNIQUE project_id + state index, onboarding_steps UNIQUE project_id+step_name + project_id/status indexes, archived_projects append-only with project_id/archived_at indexes).
- [x] Application services: `RoutingService` (upsert idempotent by pattern, disable, `match` with case-insensitive substring + `re:<regex>` pattern support picking highest-priority active rule, invalid regex silently skipped), `BudgetPolicyService` (upsert with token/cost clamping at 0, set_state, get_for_project), `OnboardingService` (DEFAULT_STEPS tuple of 5 canonical steps, `seed_defaults` idempotent by step_name, `mark_status` auto-timestamps `completed_at` on COMPLETE/SKIPPED, `progress` returns `(done, total)`), `ArchiveService` (archive, is_archived, list).
- [x] Dashboard routes + HTMX fragments: portfolio-wide routing (`/chief-of-staff/routing` + `/disable`), budgets (`/chief-of-staff/budgets` + `/state`), archive (`/chief-of-staff/archive`); project-scoped onboarding wizard (`/projects/{pid}/chief-of-staff/onboarding` + `/seed` + `/{step_name}/status`). CSS: rule status-coloured borders (active=green, disabled=grey), budget state-coloured borders with red-tinted background on exceeded, onboarding step status-coloured borders (complete=green, skipped=grey, pending=amber), archive reason-coloured borders (shipped=green, abandoned=grey, merged=blue), monospace pattern code tags, inline state/status selector forms, progress counter `done/total` in onboarding header.
- [x] Dashboard slots: portfolio-wide Chief of Staff surfaces (routing, budgets, archive) at `/chief-of-staff/*`; project detail page adds 1 per-project onboarding slot.
- [x] Tests: 51 new (domain 11 + infra 7 + services 13 + routes 20) — entity invariants (is_enabled, blocks_cycles for both EXCEEDED+PAUSED, is_done for COMPLETE+SKIPPED), SQLite UPSERT idempotency (pattern/project/step), list_active priority ordering, substring+regex+priority routing match, negative token/cost clamp, seed_defaults idempotency, auto-completed_at on mark_status, progress counter, route-level enum fallback (status→active, reason→other), 400 on unknown onboarding status, 404 on missing rule/policy/step; **2000 total passing**.

### Phase L — Polish & portfolio (~1 cycle) ✅ Done

- [x] Cross-project refactor programs — domain entity (RefactorProgram, RefactorProgramStatus proposed/active/completed/cancelled), migration v021 with UNIQUE title, `target_projects_text` newline-packed, SQLite UPSERT preserving id, service with timestamp auto-setting on activate/complete/cancel + dedupe on add_project, 7 portfolio-wide routes, state-coloured template.
- [x] Semantic memory retrieval (opt-in) — domain with `.matches(query, tag)` substring+tag match, migration v022 with tags_text + enabled flag + project_id index, repo.list_all(project_id) includes portfolio-wide, service.search() with enabled filter, dual-scope template (portfolio + per-project) via Jinja `{% set fragment_id %}`, enable/disable toggle that routes back to correct scope.
- [x] Prompt-library UI with audit trail — versioned PromptTemplate (bump only on body or role change), PromptAuditEntry with CREATE/UPDATE/DEPRECATE/RESTORE actions, migration v023 with UNIQUE name + append-only audit, idempotent deprecate/restore, /prompt-library/audit filtered by name, HTMX fragment with deprecate+restore forms, action-coloured audit entries.
- [x] Autonomy-spectrum config — AutonomyLevel enum (manual/assisted/supervised/autonomous) with `.rank` + `.requires_human_before_action`, AutonomyConfig with `.gate_label` per level, migration v024 with UNIQUE(project_id, role), per-project routes at `/projects/{id}/autonomy`, 400 on invalid level, state-coloured rows.
- [x] Docs: `docs/ROLES-OVERVIEW.md` summarising all roles and their dashboard surfaces; refreshed top-level `CLAUDE.md` to reference Phase A–L completions; this file updated to mark Phase L ✅ Done.
- [x] Tests: 103 new (domain 22 + infra 14 + services 27 + routes 40) — refactor program dedupe + 9 route cases, semantic search tag+enabled filters + 8 route cases, prompt version idempotency + 9 route cases (incl. /audit), autonomy project isolation + 5 route cases; **2103 total passing**.

---

## 7. Technical decisions to lock in early

- **Codename uniqueness is portfolio-wide.** Prevents "which Alice?" confusion.
- **Retired codenames stay linked to their memory** forever; no memory destruction without explicit action.
- **Memory is append-only internally;** edits create a new entry with `supersedes` pointing to the old one. Dashboard hides superseded by default.
- **Prompts live in files under version control**, not inlined in Python. Enables A/B-ing and prompt diffs in PRs.
- **Dashboard chat is additive**, not a replacement for Mattermost. Both write to the same conversation store.
- **Autonomy defaults are conservative**; humans opt in to higher autonomy per project × role.
- **Cycle type is a first-class field**, not a flag on the dev cycle.

---

## 8. What I'd do first

If only one change shipped this week:

> Phase A.1 — the codename assignment + three-layer memory. Everything else (new roles, chat, intel, quality) depends on this foundation and gets cheaper once it's in place.

After that, ship **Phase B (chat) before any new role**. You can't manage the swarm from the dashboard without chat; you can't give an agent a personality without identity; you can't measure improvements without per-role-per-project memory.

---

## 9. Open questions to confirm with the operator

1. **Codename pool** — do we want culturally diverse names by default, or themed pools (Greek mythology, inventors, plants…)?
2. **Chat substrate** — dashboard-native only, or always mirrored to Mattermost?
3. **Autonomy defaults per role** — confirm the table in §5.3.
4. **Scout portfolio vs. per-project** — default to portfolio-scoped and override per-project, agreed?
5. **Prompt-library editability** — read-only to start, or editable from day one with audit?
6. **Integrations priority** — PostHog? Sentry? Linear? Figma? (drives Analyst + Designer roadmap).
7. **Public URL for the dashboard** — who can reach it? RBAC needed for multi-user, or solo for now?
8. **Memory exportability** — do we want a `swarm memory export --project X` for audit / transfer?

These answers shape Phases C onward. None of them block Phase A.
