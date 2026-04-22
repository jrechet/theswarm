# Scout (Intel Officer) — NEW role

> Codenamed like the others (e.g., `Echo`, `Pax`, `Rune`). Shared across projects by default (portfolio-level intel), can be project-scoped when a project warrants a dedicated Scout.

## Why this role

Currently, "veille" (market + tech intel) is bolted on to PO and TechLead. That works for small teams, but:
- PO ends up drowning in feed noise instead of shaping product.
- TechLead reviews + architecture suffer when it also has to scan HN, arXiv, GitHub trending.
- There is no single home for _"what changed in the world today that matters to us"_.

Scout owns **sensing**; PO and TechLead own **deciding**.

## Responsibilities

### 1. Portfolio-wide radar

- GitHub Trending + topic feeds matched to each project's language/framework.
- HN / Lobste.rs / Reddit (curated subs) / Product Hunt / Indie Hackers / arXiv / Papers With Code.
- X / Mastodon / BlueSky lists for curated thought leaders (OPT-IN per project).
- RSS/Atom for blog feeds (engineering blogs, vendor blogs, security advisories).

### 2. Competitive watch (delegated from PO)

- Per-project `competitors.yaml` declares repos / sites / changelogs / handles to track.
- Daily diff job; classifies as `threat` / `opportunity` / `noise` / `mirror-ours`.

### 3. Security & compliance watch

- Feeds into TechLead: CVE advisories for tracked deps (GitHub Security Advisories, OSV, PyPI Safety DB, NVD).
- Regulatory watch (when applicable): GDPR, EU AI Act, sectoral standards declared in project policy.

### 4. Curation over firehose

- Scout never dumps raw feeds. Everything is:
  - **Deduplicated** (URL + content hash).
  - **Classified** (category, project-relevance score, urgency).
  - **Summarized** (≤ 3 sentences).
  - **Tied to an action** (proposal to PO, issue to TechLead, mention to another role, or "FYI only").

### 5. Insight graph

- Items link to each other (same story appearing on HN and vendor blog and GitHub → one cluster).
- Graph surfaces "trending topics in our space" without us defining them.

### 6. Know-what-we-don't-know

- Detects **absence**: "Our project touches OAuth but our memory has no OAuth security items" → flag a learning gap.
- Proposes research spikes to PO.

## Interactions

- **→ PO.** Product-relevant signals become proposals on the PO inbox.
- **→ TechLead.** CVE + framework / dependency signals become tech-radar items or `deps:security` issues.
- **→ Architect.** Pattern / paradigm shifts become ADR drafts.
- **→ Dashboard.** Portfolio news feed; per-project filter; saved searches.

## Memory patterns

- **Scout memory** is largely **shared** (portfolio-scoped) but filtered per project on surface.
- `sources` — subscribed feeds with health + signal-to-noise.
- `clusters` — grouped stories over time.
- `signals` — annotated items linked to action taken.

## Dashboard surfaces

- **Intel feed** (global + per-project views) with filter chips: threat / opportunity / cve / framework / paper / noise.
- **Saved searches** with alerts.
- **Source health** (feed last-ok, error rate, signal rate).
- **"Propose to PO" / "Open issue for TechLead"** buttons on every item.

## New tools

| Tool | Purpose |
|---|---|
| Feed aggregator (`feedparser`) | RSS/Atom |
| WebFetch / WebSearch | One-off lookups |
| `gh search` | GitHub trending, repo search, code search |
| Embedding-based clustering | Deduplicate and group items |
| Classifier prompt (Haiku) | Cheap first-pass routing |

## Success metrics

- Signal-to-noise on Scout feed ≥ 0.3 (measured by "action taken" on items).
- Time from competitor release → classified item ≤ 6h.
- Time from CVE disclosure on tracked dep → TechLead ticket ≤ 24h.
- < 5 duplicates surfaced per week.

## Rollout

1. **Core radar**: GitHub trending + HN + RSS + GH Security Advisories. Classifier v1 (Haiku).
2. **Competitive watch** (takes over from PO).
3. **Insight graph + clustering.**
4. **Gap detection** ("we touch X but have no memory of X").
5. **Dashboard feed with actions + saved searches.**
