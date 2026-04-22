# Release Manager — NEW role

> Codenamed (e.g., `Tomás`, `Ula`, `Bex`). Per project.

## Why this role

Merging a PR ≠ shipping. Someone must own versioning, tagging, rollout orchestration, release cadence, and rollback decisions. Without this, projects ship whenever TechLead merges, which confuses users (no changelog, no versioning, no rollback plan).

## Responsibilities

### 1. Versioning policy

- Per project: SemVer? CalVer? Rolling? Declared in project config.
- Release Manager enforces version bumps in PR titles / labels. Blocks merge if missing.

### 2. Release cadence

- Daily / weekly / on-demand, per project. Can be overridden.
- Scheduled release cycles (distinct from dev cycles) bundle merged PRs into a release.

### 3. Rollout strategy

- Canary → progressive → full, or straight-to-prod, per risk profile (SRE weighs in).
- Automatic monitoring window after each rollout; rollback if alert fires within the window.

### 4. Changelog

- Auto-generates from merged PRs using conventional commits + TechLead's ADR index.
- Writer polishes the customer-facing release notes.

### 5. Feature flags

- Owns flag inventory; enforces flag lifecycle (created → rolled-out → cleaned up). Opens `flag:cleanup` stories for zombie flags.

### 6. Communication

- Release announcement channel (Mattermost / Slack / email / in-app banner), per project.
- Ties release → changelog → demo artifacts so users can see what's new.

### 7. Compliance hooks

- Verifies Security has signed off on releases touching PII/payment.
- Verifies SRE has acknowledged the rollout.

## Interactions

- **Gate between TechLead merges and production.**
- **← QA.** Needs green on regression + perf + a11y + security.
- **← SRE.** Rollout method + monitoring plan.
- **← Writer.** Release notes.

## Memory patterns

- Per-project-per-Release: `versions`, `rollouts`, `flags`, `rollbacks`, `cadence_history`.

## Dashboard surfaces

- **Release calendar** per project.
- **Flag inventory.**
- **Rollback button** with confirmation + audit.
- **Release history** with blast radius (files, surfaces, users).

## New tools

| Tool | Purpose |
|---|---|
| `gh release` | Tag + release |
| Feature flag store (GrowthBook, LaunchDarkly, or in-house) | Flag lifecycle |
| Simple canary via traffic weight (SRE) | Progressive rollout |

## Success metrics

- 100% of releases have a changelog.
- Rollback MTTR ≤ 15 min.
- Zombie flags (> 30 days, 100% rolled out) = 0.
- Release note open-rate (external users) — grow over time.

## Rollout

1. **Foundation.** Codename, versioning policy, release cycle type.
2. **Changelog automation.**
3. **Rollout strategies + rollback flow.**
4. **Flag lifecycle.**
5. **Release comms.**
