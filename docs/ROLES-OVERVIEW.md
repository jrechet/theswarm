# Roles Overview

*Snapshot of every role in the swarm and the dashboard surface it owns. For detailed role roadmaps, see `docs/roles/<role>-next.md`.*

## How to read this

Each role has:

- **Purpose** — the cognitive function it owns.
- **Dashboard surface** — the panels and routes that expose its work.
- **Key entities** — domain objects it manipulates.
- **Autonomy default** — human gating baseline; override per project at `/projects/{id}/autonomy`.

## Portfolio-level roles

These roles operate across all projects in the swarm.

### Architect
- **Purpose** — portfolio-wide technical direction: paved roads, ADRs that bind multiple projects, direction briefs.
- **Dashboard** — `/architect` (paved-road rules, portfolio ADRs, direction briefs).
- **Entities** — `PavedRoadRule`, `PortfolioADR`, `DirectionBrief`.
- **Autonomy default** — supervised.

### Chief of Staff
- **Purpose** — routing work, enforcing portfolio budgets, onboarding new projects, archiving completed ones.
- **Dashboard** — `/chief-of-staff` (routing rules, budget policies, onboarding checklist, archive log).
- **Entities** — `RoutingRule`, `BudgetPolicy`, `OnboardingStep`, `ArchivedProject`.
- **Autonomy default** — assisted.

### Scout
- **Purpose** — external intelligence: watch releases, papers, competitors; cluster findings into briefs.
- **Dashboard** — `/scout` (sources, feed items, clusters).
- **Entities** — `IntelSource`, `IntelItem`, `IntelCluster`.
- **Autonomy default** — autonomous (read-only ingestion).

## Project-level roles

These roles work inside a project context.

### PO (Product Owner)
- **Purpose** — outcome framing, backlog shaping, stakeholder comms, policy guardrails.
- **Dashboard** — `/product` (proposals, OKRs, policy, digest, signals).
- **Entities** — `Proposal`, `OKR`, `Policy`, `Signal`, `Digest`.
- **Autonomy default** — assisted (proposals need human OK).

### TechLead
- **Purpose** — technical review, ADRs, debt register, dependency radar, second-opinion gate.
- **Dashboard** — `/techlead` (ADRs, debt, dep findings, review verdicts, critical paths).
- **Entities** — `ADR`, `Debt`, `DepFinding`, `ReviewVerdict`, `CriticalPath`.
- **Autonomy default** — supervised.

### Dev
- **Purpose** — build stories; disciplined TDD; self-review; refactor preflight; coverage deltas.
- **Dashboard** — `/dev-rigour` (TDD artifacts, thoughts, self-review, preflight, coverage).
- **Entities** — `DevThought`, `TddArtifact`, `RefactorPreflight`, `SelfReview`, `CoverageDelta`.
- **Autonomy default** — supervised (review-before-merge).

### QA
- **Purpose** — E2E tests, flake tracking, quarantines, quality gates, outcome cards.
- **Dashboard** — `/qa` (test plans, archetype mix, flake log, quarantines, gates, outcome cards).
- **Entities** — `TestPlan`, `FlakeRecord`, `Quarantine`, `QualityGate`, `OutcomeCard`.
- **Autonomy default** — autonomous (quarantine/gate).

### Designer
- **Purpose** — design system tokens, component inventory, design briefs, visual regression, anti-template audits.
- **Dashboard** — `/designer` (tokens, components, briefs, visual regression, anti-template checks).
- **Entities** — `DesignToken`, `Component`, `DesignBrief`, `VisualRegression`, `AntiTemplateCheck`.
- **Autonomy default** — supervised.

### Security
- **Purpose** — threat models, data inventory, findings, SBOMs, AuthZ matrix.
- **Dashboard** — `/security` (threat models, data inventory, findings, SBOM, AuthZ).
- **Entities** — `ThreatModel`, `DataInventoryEntry`, `SecurityFinding`, `SBOM`, `AuthZRule`.
- **Autonomy default** — assisted (critical findings need human).

### SRE
- **Purpose** — deployments, incidents, cost tracking.
- **Dashboard** — `/sre` (deployments, incidents, cost).
- **Entities** — `Deployment`, `Incident`, `CostEntry`.
- **Autonomy default** — supervised.

### Analyst
- **Purpose** — metric definitions, instrumentation plans, outcome observations.
- **Dashboard** — `/analyst` (metrics, instrumentation, observations).
- **Entities** — `MetricDefinition`, `InstrumentationPlan`, `OutcomeObservation`.
- **Autonomy default** — autonomous (metrics are observational).

### Writer
- **Purpose** — doc artifacts, quickstart checks, changelog entries.
- **Dashboard** — `/writer` (docs, quickstart, changelog).
- **Entities** — `DocArtifact`, `QuickstartCheck`, `ChangelogEntry`.
- **Autonomy default** — supervised.

### Release
- **Purpose** — version tracking, feature flags, rollback actions.
- **Dashboard** — `/release` (versions, flags, rollbacks).
- **Entities** — `ReleaseVersion`, `FeatureFlag`, `RollbackAction`.
- **Autonomy default** — supervised.

## Portfolio-level meta surfaces (Phase L)

These surfaces cut across all roles.

### Refactor programs
- **Purpose** — coordinate refactors across multiple projects (e.g. "move all APIs to v2 auth").
- **Dashboard** — `/refactor-programs` (proposed / active / completed / cancelled programs, add/remove target projects).
- **Entities** — `RefactorProgram`.

### Semantic memory
- **Purpose** — opt-in retrieval-friendly notes (tag + substring search). Portfolio-wide and per-project.
- **Dashboard** — `/semantic-memory` (portfolio) and `/projects/{id}/semantic-memory` (project-scoped; includes portfolio-wide entries).
- **Entities** — `SemanticMemoryEntry`.

### Prompt library
- **Purpose** — versioned prompts with a full audit trail (create/update/deprecate/restore). Portfolio-wide.
- **Dashboard** — `/prompt-library` (templates); `/prompt-library/audit?name=` (history).
- **Entities** — `PromptTemplate`, `PromptAuditEntry`.

### Autonomy spectrum
- **Purpose** — per-(project, role) gating level: manual / assisted / supervised / autonomous.
- **Dashboard** — `/projects/{id}/autonomy`.
- **Entities** — `AutonomyConfig`.

## Autonomy levels

| Level | Gating behaviour |
|-------|------------------|
| `manual` | Human-initiated only — the agent does not act. |
| `assisted` | Agent proposes; human confirms every step. |
| `supervised` | Agent acts; human reviews before merge. |
| `autonomous` | Agent acts and ships unless blocked. |

Defaults are conservative; override per project at `/projects/{id}/autonomy`. Higher autonomy requires an opt-in because every role's memory is additive and irreversible — once shipped, decisions are logged in the audit trail and the prompt library.
