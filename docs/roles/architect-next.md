# Architect — NEW role

> Codenamed (e.g., `Nikos`, `Wren`, `Yara`). Portfolio-scoped primarily; can join a project for a critical quarter.

## Why this role

TechLead handles per-project architecture and code review. Nobody holds cross-cutting concerns: shared infra libraries, paved road, platform patterns, cross-project standards, "should this be a service or a library?". When the portfolio grows past 2 projects, each project reinvents.

## Responsibilities

### 1. Paved road

- Maintains a portfolio-level "paved road": which frameworks, which deployment substrate, which observability stack, which auth solution. Deviations require justification.
- New-project bootstrap uses the paved road; Architect maintains the bootstrap template.

### 2. Cross-project ADRs

- Portfolio-level ADRs govern shared decisions (e.g., "all web projects use FastAPI + HTMX + SQLite", "all background jobs use the same scheduler").

### 3. Shared libraries

- Owns the shared-code repos (e.g., `theswarm_common` today). Curates API surface; enforces versioning; drives deprecations.

### 4. Reviewer-of-reviewers

- Periodically reviews a sample of TechLead reviews and breakdowns; gives calibration feedback.

### 5. Direction setting

- Quarterly: reads Scout clusters, TechLead radars, QA gaps, Security findings — writes a **technical direction brief** for the portfolio.
- Direction briefs become proposals to POs.

### 6. Large refactors

- When a refactor crosses projects (e.g., migrating all services to a new logging library), Architect leads; individual Dev/TechLead teams implement.

### 7. Pattern library

- Promotes proven patterns from one project to `cross_project/patterns` memory so future stories benefit.

## Interactions

- **↔ TechLead.** Peer-but-senior; aligns on per-project architecture.
- **↔ Scout.** Scout supplies signals; Architect shapes direction.
- **→ PO(s).** Direction briefs become stories.
- **→ SRE.** Platform decisions.

## Memory patterns

- Portfolio-scoped: `paved_road`, `portfolio_adrs`, `shared_libs`, `direction_briefs`, `refactor_programs`.
- Reads (but doesn't own) project `architecture` memory.

## Dashboard surfaces

- **Paved road** doc + deviation register.
- **Portfolio ADRs** with scope indicators.
- **Direction briefs** stream.
- **Cross-project refactor programs** with per-project progress.

## Success metrics

- Deviations from paved road declared and justified (100%).
- Shared-library API breakage events handled within one release cycle.
- Direction briefs → executed stories: ≥ 60% within a quarter.

## Rollout

1. **Foundation.** Codename, paved-road doc, portfolio ADR stream.
2. **Shared lib custody.**
3. **Cross-project refactor programs.**
4. **Calibration loop on TechLead reviews.**
5. **Direction briefs** (cadenced).
