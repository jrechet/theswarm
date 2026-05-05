# Dashboard UI/UX Audit (KISS — but right)

> Snapshot taken 2026-05-05 against `https://bots.jrec.fr/swarm` after the prod incident where sprint draft silently failed with "Failed to draft. Try again."

## Top-level findings

| Sev | Area | Finding | Recommended fix |
|-----|------|---------|-----------------|
| CRITICAL | Error UX | Backend errors collapse to one opaque toast; user can't recover. | Surface server `detail` and link to relevant config (✅ shipped for sprint composer + Settings) |
| CRITICAL | Setup | API keys / tokens require SSH + redeploy to set. | Settings page in-app (✅ shipped) |
| HIGH | Discoverability | 200+ routes, no first-run flow. New project page = empty form, no checklist. | Add a "Setup checklist" card on dashboard until ANTHROPIC_API_KEY + GITHUB_TOKEN + 1 project all green |
| HIGH | Status truth | Sidebar shows "Live updates" badge but does not call out when SSE auth/connection is failing. | Color the dot red + tooltip with last error |
| HIGH | Page weight | Project detail page renders **15+ collapsible sections** before the user sees their first sprint. Cognitive load is high. | Default-collapse advanced sections under one "Advanced" disclosure; keep Sprint composer + Sprints + Configuration above the fold |
| MED | Form affordance | "Models (phase=model, comma-separated)" — pure free-text for a structured field. No validation feedback until 422. | Render four labeled selects (PO/TechLead/Dev/QA) with model dropdown |
| MED | Empty states | Many fragments load with `Loading…` then show "No data". Two states feel the same. | After load, replace skeleton with explicit empty-state CTA ("Create your first OKR") |
| MED | Buttons | Primary/secondary distinction inconsistent: "Run Cycle" and "Delete" share the same blue. Delete is destructive. | Reserve filled-blue for primary, outline-red for destructive |
| MED | Mobile | Sidebar collapses but role accordions overflow at 375. | Stack accordions full-width below 480px; suppress sidebar by default |
| LOW | Typography | All headings same weight; no hierarchy between H1 page title and H2 cards. | One step heavier on H1, one step smaller on H2 |
| LOW | Iconography | Nav uses Unicode glyphs (⬡ ◇ ▤ ◉ ↻ etc) — readable but not aligned visually | Optional: switch to a simple icon set or lock to a single Unicode block |

## Surface-by-surface notes

### Dashboard `/`
- ✅ Active cycles + recent + stats — clear at a glance.
- ⚠ "Today's demo" carousel auto-loads but offers no fallback when no demo exists; replace with a friendly "No demos yet — run a cycle to record one."
- ⚠ Two real-time mechanisms (HTMX polling + SSE). Pick one per card; document why.

### Projects list `/projects/`
- KISS-pass: minimal. Add a sortable table header (name / repo / last cycle / cost / status).

### Project create `/projects/new`
- Minimal — good. Add a help banner: "We'll auto-detect the framework and suggest models for your stack. You can change them later in Configuration."

### Project detail `/projects/{id}`
This page is the cockpit. Today it shows, in order: Sprint composer, Sprints, Configuration, Controls, Secrets, Team, Chat, Recent Cycles, then 14 role accordions. **15+ sections.**

KISS rework:
1. **Hero card**: project name + actions (View demos / Memory / Pause / Run / Delete).
2. **Above the fold**: Sprint composer + Sprints + last cycle status.
3. **Configuration & Secrets** in a sticky right sidebar at ≥1280px, full-width below.
4. **Roles**: collapsed under one "Advanced — agent role surfaces" disclosure. Open one at a time.
5. **Recent cycles**: separate timeline section, lazy-loaded.

### Sprint composer
- ✅ Now surfaces server detail and links to Settings on auth failure.
- TODO: Add a "Show example prompt" link under the textarea — first-run users do not know what level of detail to provide.
- TODO: Disable "Draft issues" until the textarea has ≥10 chars.
- TODO: Show token / cost estimate before "Confirm" so the user knows what they're paying.

### Cycles
- Filter by project: works. Add filter by status (running / completed / failed) — this is the question users actually ask.
- The replay scrubber is novel; consider a tooltip first-time hint.

### Reports & Demos
- Demo player: clicking a story card to seek video is great. Surface that affordance with a "Click any story to jump in the video" hint on first open.
- Demo compare side-by-side: keep, but only expose when 2+ demos exist.

### Role surfaces (Phases C–L)
14 role groups, each with 2–6 sub-tabs. Today they live as accordions on the project detail page **and** as standalone routes — duplicated.
- Consolidate: one entry point per role from the sidebar, no duplicated accordion.
- Each role landing page: top-line metric + 1-line description + tabs for sub-features.

### Settings (NEW)
- ✅ Cards per setting with masked current value, save / clear buttons.
- ⚠ Password input prevents paste-as-plaintext on some browsers — confirm paste works on Firefox/Safari.
- TODO: live "Test connection" button next to Anthropic + GitHub.

### HITL audit
- Today: list of pending decisions. Add a "Decide" inline action (approve/reject) — no need to bounce to a sub-page.

## KISS principles applied here

1. **One source of truth per concept.** Settings, secrets, schedules all currently live in 2+ places — collapse to one.
2. **Default to hiding.** New users should see ≤7 surfaces at first paint. Power users can expose more via persistence settings.
3. **Errors are first-class UI.** Every failure path must be reachable, descriptive, and actionable — not a `console.error` and a vague toast.
4. **Loading != empty.** Distinguish skeletons from "nothing to show yet" empty states with explicit copy + CTA.
5. **Destructive actions are red and confirmed.** Today Delete is the same color as Run.

## Quick wins (≤1 day each)

1. Settings page (✅ done)
2. Sprint composer error → server detail + Settings link (✅ done)
3. Setup checklist card on dashboard
4. Color destructive buttons red + add confirm dialogs
5. Default-collapse role accordions on project detail
6. SSE status badge: red on disconnect with tooltip
7. Disable "Draft issues" button until input ≥10 chars
8. Add filter-by-status to /cycles

## Larger reworks (≥1 sprint)

A. **Project detail IA rework** — sidebar + accordion-collapse advanced
B. **Roles consolidation** — single sidebar entry per role, no duplicated accordion
C. **Auth + permissions** — currently anonymous; gate Settings + project mutation behind login
D. **Test "Test connection" buttons** for every external service (Anthropic / GitHub / Mattermost / Seq)
E. **First-run tour** — Shepherd.js or similar, 5 steps, dismissible
