# PO (Product Owner) — Next

> **Codename convention.** Every PO instance assigned to a project gets a unique human first name (e.g., `Alice`, `Priya`, `Hugo`). That name is the agent's identity in dashboard, DMs, memory, and retrospectives. See `dev-role-dashboard.md` for the name registry.

## Today (what exists)

- Runs twice per cycle: morning (picks backlog, writes `daily_plan`) + evening (validates `demo_report`, writes `daily_report`).
- StateGraph in `src/theswarm/agents/po.py`. Prompts inline.
- Receives Mattermost DMs via `persona.py` with NLU intents (`create_stories`, `run_cycle`, `show_plan`, `show_report`, `add_repo`, ...).
- Memory: reads role-filtered `architecture`/`learnings`; writes retrospective entries after cycles.

## Gaps

- **Reactive only.** Does nothing between cycles; cannot spot opportunities, risks, or drift.
- **No competitive / market awareness.** Has no view of what competitors ship, what's trending on GitHub, what users complain about.
- **No user / stakeholder model.** Doesn't know who asked for what, who wins/loses with each decision, or who to update.
- **No OKRs / outcome framing.** Selects issues mechanically; no link between sprint choice and business outcome.
- **Single channel.** Mattermost DM only. No email digests, no dashboard-native chat, no weekly summary.
- **No story quality bar.** Stories are generated from free-text descriptions with no acceptance-criteria enforcement, no edge-case enumeration, no non-functional requirements.

## Next responsibilities

### 1. Continuous product intelligence (Veille produit)

- **Competitor watch.** Maintain a per-project `competitors.yaml` (repos, sites, RSS, Product Hunt handles). Daily pass:
  - Poll competitor GitHub repos: new releases, closed milestones, merged PRs labeled `feature`, changelog diffs.
  - Scrape their changelog/blog with a `scraper` tool (respect robots.txt + rate limits).
  - Summarize deltas, classify as `threat` / `opportunity` / `noise`.
- **Ecosystem watch.** Weekly pass over GitHub Trending (filtered by language + topics of the project), HN front page (filtered), arXiv categories, Reddit subs, Product Hunt launches.
- **Customer signal.** If project has public issue tracker / Discord / Slack: aggregate top-voted requests, group by theme, surface the top-3 unmet needs.
- **Output:** a `PO insights digest` (JSONL + markdown), surfaced on the dashboard and as a weekly DM.

### 2. Backlog shaping

- **Opportunity → Story pipeline.** Insights become `proposed stories` with evidence (`source_url`, `evidence_excerpt`, `confidence`). Dashboard has a **Proposals** column with Approve / Reject / Defer / Ask-human actions.
- **Story quality checklist (automatic).** Every story must have: problem framing, user persona, acceptance criteria (Given/When/Then), non-goals, non-functional considerations (perf, a11y, security, i18n), risk list, rough T-shirt size.
- **Story deduplication.** Before creating, semantic-search existing issues + closed issues + proposals cache.
- **"Why now" justification.** Each selected story of the day carries a one-liner ("beats competitor X", "fixes churn signal Y", "unblocks Z").

### 3. Outcome framing

- **Project OKRs.** Dashboard-editable OKRs per project. PO aligns sprint selection to the closest OKR; retros report movement.
- **Success metrics per story.** Where possible, the story declares a leading indicator (e.g., "dashboard load < 800ms", "sign-up conversion +5%"). QA / Analyst roles verify post-ship.

### 4. Stakeholder communication

- **Daily brief** (dashboard widget + optional email): what was shipped, what's next, top risk, one decision needed.
- **Weekly digest** auto-generated every Friday: outcomes, competitor deltas, user signals, proposed next-week focus.
- **Ask-me-anything chat.** Dashboard chat thread pinned per project. User can `@Alice` (the PO codename) from the dashboard and get a reply using that PO's memory.

### 5. Governance & ethics

- **Policy memory.** PO maintains a `policy.md` per project: ethical constraints, scope boundaries, "never ship" list, licensing, PII handling. Used as a hard filter on story generation.
- **Escalation rules.** If a story touches a policy edge case, the PO must flag it and request human confirmation before dispatch.

## New tools / integrations

| Tool | Purpose |
|---|---|
| `market-research` skill | Already available — invoke for competitor and industry scans |
| `WebFetch` / feed reader | Competitor changelog + RSS |
| `gh search` / GitHub API trending | Repo and code search |
| Semantic search over backlog | Story dedup (pgvector or FAISS, starts on-disk) |
| Lightweight scraper (Playwright headless) | Competitor web content |
| ICS/email | Weekly digest delivery |

## Memory patterns

- **Per-project-per-PO memory** (keyed `(project_id, codename)`):
  - `competitors` — one entry per tracked competitor, updated on each scan.
  - `stakeholders` — who cares about what, communication preferences.
  - `policy` — hard product rules.
  - `signals` — observed customer / market signals with timestamps.
  - `decisions` — every significant sprint decision with rationale and outcome check.
- **Promote to global** when an insight generalizes (e.g., "users reject auto-push notifications by default" → `cross_project/product_principles`).

## Dashboard surfaces

- **Inbox** per PO: proposals, asks from users, insights awaiting review.
- **OKR panel** editable by humans.
- **Competitor board** — timeline of competitor deltas with threat classification.
- **Chat** — DM-like thread scoped to `(project, codename)`.
- **Policy editor** with diff view.

## Success metrics

- Proposal→accepted story conversion ≥ 40%.
- Time from competitor release → PO-surfaced proposal ≤ 24h.
- ≥ 1 outcome metric declared per shipped story.
- Weekly digest read-rate (opened + clicked on proposals).
- Drift: % of sprint work tied to an explicit OKR.

## Rollout (4 phases)

1. **Foundation.** Codename assignment, per-project memory namespace, policy file, story quality checklist.
2. **Intelligence.** Competitor watch + ecosystem watch jobs (scheduled via existing `CronScheduler`). Proposals inbox on dashboard.
3. **Communication.** Dashboard chat thread, weekly digest generation, optional email.
4. **Governance.** OKRs, outcome metrics wiring with QA / Analyst, policy enforcement at story generation.
