# V3 — one product (2026-10)

Decision (owner, 2026-10-06): TheSwarm is the product, and it is sold to
customers. "I have to handle multiple customers with this, multiple
projects. Ils ont un compte, ils se connectent, ils peuvent consulter les
démos et voir l'avancement du projet." The UI, two generations deep,
"looks quite bad, not modern, not coherent" — it gets one shell, one
design system, one vocabulary, and the two older generations are deleted.

The owner's answers, 2026-10-06:

| Question | Answer |
|---|---|
| What is a customer? | One instance; a customer's members sign in and see only their customer |
| What may members do? | Watch: progress, demos, their own requests. The owner writes features and presses Play |
| Look | Modern control room, light and dark |
| V1 | Delete it all |
| A **Request** is the one thing a customer writes | yes |
| The owner sees spend per customer and per cycle; customers never do | yes |
| A member sees a running cycle as four plain steps, never the theater | yes |

The prototype the owner approved: a Design canvas of eleven artboards —
both roles, both themes, the design-system sheet. Its sources are kept in
`docs/design/v3/` (`*.dc.html`, the canvas format; open them beside this
plan, they are plain HTML with inline styles).

## What exists (2026-10-06)

- **V1**: 95 templates, 14 "role" surfaces, dashboard, projects, cycles,
  reports, chat, settings — Pico CSS + HTMX, `templates/base.html`,
  `static/css/dashboard.css`, 14 JS files. 32 route files, 105 page routes.
- **V2**: 6 templates (`templates/v2/`), Tailwind v4 "atelier" tokens,
  Plex vendored. Owns `/`, `/r/{owner}/{name}`, `/r/…/memory`,
  `/c/{cycle_id}` (the theater). Its header links to "Legacy".
- **Doors**: `auth.py` (signed cookie, `mint_session(login)`), the access
  key, GitHub OAuth admitting `SWARM_OWNER_LOGIN` only.
- **Data**: `projects` (the legacy registration, auto-created by the V2
  repo page), `cycles` (v032), `eval_runs`, the report store, the cycle
  event store. No customer, no member, no request anywhere.

Three navigations, two vocabularies (project / repo, cycle / play), one
owner and one shared key. Nothing is wrong with the engine; the surface
never decided what the product is made of.

## The product

**Hierarchy**: Customer → Project → Feature → Cycle → Demo. Plus Request,
a customer's need in their own words. Every screen lives at one of those
levels and the URL says which.

| Word | Meaning |
|---|---|
| Customer | a company the owner works for; its members sign in and see only it |
| Project | a GitHub repository the swarm may work on, inside one customer |
| Request | a need a member wrote; the owner turns it into a feature (or declines it) |
| Feature | a GitHub issue the owner wrote; the swarm breaks it into sub-tasks |
| Cycle | one run of the four agents on a feature |
| Demo | what a cycle delivered: the video, the gates, the verdict, the PRs |
| Verdict | verified, unverified, broken — what the running app said (unchanged, M6 of the runtime plan) |

**Two roles.** The *owner* (`SWARM_OWNER_LOGIN`, or the access key) sees
everything, writes features, presses Play, administers customers. A
*member* belongs to one customer and watches: its projects' progress,
its demos, its requests; writes requests. Nothing else — no settings, no
Play, no theater, no cost, no API.

**One shell**: a left rail (home, requests, the customers and their
projects, settings, Claude's health, the signed-in person), a top bar
(breadcrumb left, the level's actions right), the content. A member gets
the same shell with one customer in it. On a phone the rail becomes a
strip on top, columns stack, tables scroll sideways.

**Five screen families** (owner):

1. **Home** — Now (running cycles), To review (demos since the last
   visit), Requests waiting, the customers (projects, what is in flight,
   this month's spend).
2. **Project** — header, composer ("write a feature" → issue, Create
   only / Create and play), the board (Requests · Ready · Building · In
   review · Delivered), the trend of the last cycles, recent cycles.
   `/f/{n}`: one feature, its sub-tasks, its cycles, its demo.
3. **Cycle** — the theater: phase stepper, the four agents, what
   happened, the feature piece by piece, the PRs; ends on the demo.
4. **Demo** — the player: the video, what QA measured (seven gates),
   what was built (a story per PR), who can see it.
5. **Settings** — Customers, Members, GitHub, Access and links, Claude,
   Instance.

**Member views**: Overview (progress, being built right now as four
steps, latest demos, their requests and where each stands), Demos, Your
requests, New request. The demo player is the same page as the owner's,
without cost, cycle links and PR links.

## The design system

The sheet is artboard `System.dc.html`. In the code it is
`static/v3/input.css` (Tailwind v4, the standalone binary, built by
`scripts/build-css.sh` and the Docker `css` stage) and the Jinja macros
in `templates/v3/_ui.html`. The rules:

- **Colour by meaning.** Canvas / surface / raised / border / ink, in a
  light and a dark set (the dark set under `prefers-color-scheme` and a
  `data-theme` override). Amber is the brand mark and the live signal,
  nothing else. Green = verified, red = broken, blue = in review, slate =
  waiting. Primary actions are ink on light, light on dark. 1 px borders,
  no shadows but popovers and the sign-in card.
- **Two faces**: Geist for what a person reads, Geist Mono for what a
  machine produced (ids, costs, durations, paths, request lines). Both
  vendored (OFL), no CDN at runtime — a row in `docs/DEPENDENCIES.md`.
  Scale: 28/22/16/14/13/12, labels 12 uppercase tracked, mono 12.
- **Six status words everywhere**: Running (pulsing), Verified,
  Unverified, Broken, In review, Waiting. Same chip, same colours, on the
  board, the home, the theater, the player, the member's overview.
- **Components**, each a macro: button (primary, secondary, ghost,
  danger), chip, rail item, card, gate row, phase stepper, live dot,
  avatar, customer mark, table. Rail 232, top bar 52, content padding
  28, gaps 12 / 24 / 32, radii 6 / 10.
- **Numbers never sit in prose**; a count or a cost is mono, on its own.

## The data

Migration v033 (customers, members, `projects.customer_id`; the `requests`
table comes with M5 as v034), `customer_repo.py` repositories, frozen
domain entities under `domain/customers/`:

- `customers` — `id`, `slug` (URL-safe, never twelve hex characters: a
  cycle id is), `name`, `created_at`.
- `members` — `id`, `customer_id`, `email`, `github_login` (optional),
  `display_name`, `invited_at`, `invite_token_hash`, `accepted_at`,
  `last_seen_at`, `revoked_at`.
- `projects.customer_id` — a project belongs to one customer. The
  migration creates the customer **Internal** (slug `internal`) and
  gives it every project that exists; the owner moves them from
  Settings.
- `requests` — `id`, `customer_id`, `project_id`, `member_id`, `title`,
  `body`, `status` (`received` → `planned` → `building` → `delivered`,
  or `declined`), `feature_issue_number`, `created_at`, `updated_at`.
  `planned` is set when the owner turns it into a feature; `building`
  and `delivered` follow that feature's cycles (the `CycleStarted` and
  `DemoReady` events the announcer already reads).
- **Spend** per customer is a sum over its projects' cycles
  (`cycles.cost`, already on the row) — no new table.

## The doors

- **Owner**: unchanged — GitHub OAuth for `SWARM_OWNER_LOGIN`, or the
  access key. `Authorization: Bearer` on `/api/*` stays the key only.
- **Member**: the owner invites an email from Settings; the invitation
  is a link (`/invite/{token}`, one use, 14 days) the owner sends
  themselves — no SMTP, no new dependency. Accepting it mints a member
  session (90 days). A member whose `github_login` is set may also sign
  in with GitHub. "Email me a sign-in link" on the sign-in page needs an
  SMTP relay: an owner decision, with its `docs/DEPENDENCIES.md` row,
  listed under M7 and not before.
- **The session** carries a subject: `owner:<login>` or
  `member:<id>`. `auth.py` keeps its HMAC cookie; the wall stays
  fail-safe closed; `request.state.actor` is set by the wall for the
  routes. Authorization is one function, `actor_may(actor, customer)`,
  called by every route under `/c/{slug}`, by the player and by the
  theater-as-four-steps. The owner passes everywhere. `/api/*` admits
  the owner only.

## The URLs

| URL | Who | What |
|---|---|---|
| `/` | both | Home (owner: across customers; member: their overview) |
| `/login`, `/invite/{token}`, `/logout` | — | the doors |
| `/c/{slug}` | both | a customer (owner: its projects, members, requests; member: the overview) |
| `/c/{slug}/p/{name}` | owner | the project: board, composer, Play, trend |
| `/c/{slug}/p/{name}/f/{n}` | both | one feature (member: its four steps and its demo) |
| `/cycles/{id}` | owner | the theater |
| `/demos/{id}` | both | the player |
| `/requests`, `/requests/{id}` | both | the inbox (owner) · their list and composer (member) |
| `/settings/{section}` | owner | customers, members, github, access, claude, instance |
| `/api/*` | owner | unchanged, the harness's contract |

Old links keep working: `/r/{owner}/{name}` → the project, a `/c/{id}`
that is no customer → `/cycles/{id}` (a continuation's origin → the
continuation; the slug grammar refuses twelve hex characters so the two
never collide), `/demos/{id}/play` → `/demos/{id}`. The demo announcer
posts the new player link.

## Milestones — each lands as its own PR with a demo, deployed, verified on prod

The rule stands: no demo, no merge. Demos are recorded with the local
rig (`scripts/record_v2_demo.py`, port 8095) and listed in
`docs/demos/README.md`. Each milestone updates AGENTS.md and #79.

1. **The system and the shell.** `static/v3/` (tokens, Geist vendored,
   the build), `templates/v3/base.html` and `_ui.html`, the sign-in page
   in V3, and the shell on every V2 page from day one (`v2/base.html`
   extends the V3 shell, the "Legacy" link is gone). Home V3: Now, To
   review, the projects under one customer. *Demo: sign in → home → a
   project → a running theater, light then dark.*
2. **Customers and members.** v033, the entities, Settings › Customers /
   Members / GitHub (assign a repository to a customer), invitations,
   member sessions, `actor_may`. The rail lists customers and their
   projects. *Demo: create Yakoi, add yakoi, invite Nadia, accept the
   link in a second browser, see Yakoi and nothing else.*
3. **The project and the feature.** Board with the five columns and the
   six words, composer with Create only / Create and play, trend and
   recent cycles, `/f/{n}`. The V2 repo page is replaced; `/r/…`
   redirects. *Demo: write a feature, Create and play, watch it move
   across the board.*
4. **The cycle and the demo.** The theater on V3 (stepper, agents, feed,
   the feature piece by piece, ends on the demo) at `/cycles/{id}` and
   the player at `/demos/{id}` with the seven gates and the stories.
   `/c/{hex}` redirects. V1's player, compare and approve flows are
   retired here. *Demo: a cycle from Play to the player.*
5. **What a member sees.** Member home, the four-step cycle, the demos
   list, requests (composer, list, statuses), the owner's inbox and
   "Turn into a feature" (creates the issue, links the request, flips
   it to planned; building and delivered follow the cycle events).
   "View as a customer" for the owner. *Demo: Nadia sends a request, the
   owner turns it into a feature, the demo lands on her overview.*
6. **Delete V1 and V2.** The 32 V1 route files, 95 templates, 14 JS
   files, `dashboard.css`, Pico, HTMX, the tour screenshots, their 40
   test files; `templates/v2/` and `static/v2/` once nothing extends
   them. `templates/v3/` becomes `templates/`. Every surviving behaviour
   (health page, memory viewer, the GitHub OAuth setup page, the SSE
   hub the theater uses) is already on V3 by then. *Demo: a walk of the
   whole product, every URL in the table, and `/dashboard` answering 404.*
7. **Phone, dark, measurement.** The pass at 375 px on every screen,
   dark mode on every screen, axe on the E2E smoke, a Lighthouse run on
   Home and the player, and the SMTP door if the owner wants it. *Demo:
   the product on a phone.*

The DevOps persona (D1–D4, below) starts once M4 has landed and runs
beside M5–M7: engine work, its own PRs, its own demos.

Order matters once: M2 before M3 (the project URL needs its customer),
M4 before M5 (a member's demo is the player). M1 ships first because the
shell alone makes the product read as one.

## The DevOps persona — D1 to D4

Decision (owner, 2026-10-07): a fifth persona, **DevOps**. "Fully aware
of how to build, test and deploy the project. Ensures CI/CD is
operational and can suggest improvements. Knows the connected stack —
currently mine: jrec.fr, GitHub, the Forge." It is engine work,
independent of M5–M7, and starts once M4 has landed.

**What it owns**: the pipeline, not the code. Three moments. A
*preflight* before a cycle starts (runners alive, the CI slot free,
Claude's credentials, disk, the last deploy landed). A *deploy watch*
after every merge to main (the image on the running container, `/health`
answering, else roll back or alert — what `cd.yml` does blind today, with
someone reading the outcome). A *daily ops report* with the improvements
it proposes. This session alone spent hours on exactly these: watching
deploys, clearing the CI slot, re-pinning a runner, checking Claude's
credentials.

**The stack is declared, not guessed**: a `stack:` section in
`theswarm.yaml` names the hosts (ssh), the CI providers, the registry,
the deploy method, the logs, the runner pools; credentials live in the
vault, never in a prompt. The owner's stack today: jrec.fr (Docker Swarm,
Traefik, Seq, the CI slot lock), GitHub (Actions, GHCR, secrets), the
Forge (mirror, self-hosted runners). A customer's project declares its
own later, or none — then DevOps watches GitHub only.

**Power with a leash**: it reads and diagnoses freely. Anything that
changes a machine — restart a runner, clear the slot, re-pin an image,
prune — is a **proposal** the owner approves with one click on the Home,
beside the customers' requests; the policy hook (`decide_tool_use`)
refuses every such verb outside an approved proposal. It never merges.

**In the product**: an Ops card on the owner's Home (pipeline health,
the last deploy, Claude, the proposals waiting); a fifth station in the
theater only in the cycles where it acts (preflight, deploy watch); the
TechLead's CI gate learns infra-red from code-red — a runner offline is
not the Dev's fault, the PR waits instead of going back.

**Milestones, each with its demo**:

- **D1 — The stack and the daily report.** The `stack:` declaration,
  `agents/devops.py` read-only (runners, slot, last deploy, health,
  credentials, disk, the day's harness run, failed workflow runs), the
  Ops card, the daily report on Mattermost when configured. *Demo: the
  Ops card with a real finding — the CI slot held by a stale job, as on
  2026-10-05.*
- **D2 — Preflight and deploy watch.** Go/no-go with the reason before
  the API wrapper and the harness start a cycle; every merge to main
  watched to the running container and `/health`, the alert otherwise;
  the CI gate's triage. *Demo: a merge watched to prod; a red CI triaged
  as infra, the PR left waiting.*
- **D3 — Proposals with approval.** The inbox entry, the one click, the
  policy hook's allowlist, the result reported; nothing run on its own.
  *Demo: a stale slot proposed, approved, cleared.*
- **D4 — Improvements as PRs.** From what it measures (CI durations,
  flaky tests, deploy waits, cache misses, cost per cycle): PRs on the
  workflows and the Dockerfile, reviewed by the TechLead like any other.
  *Demo: a PR that shortens the CI, measured before and after.*

**Non-goals**: DevOps never merges, never acts on a customer's machines
without a declared stack, never holds a credential outside the vault.
Two ideas the owner's question raised are folded into existing roles,
not personas: the PO writes the customer-facing summary when a demo
lands; the owner's spend view gets anomaly alerts.

## Non-goals

- Billing, invoices, Stripe. Spend is shown to the owner; money moves
  elsewhere.
- Per-cycle execution isolation. Members only watch; every cycle is
  still the owner's, run by the owner's credentials on the owner's box.
  Self-service Play for members would need that isolation first — the
  gate from the V2 product note still holds.
- Members writing features or pressing Play (owner's answer).
- Redesigning the engine, the harness or `/api/*`.

## Invariants

- The engine is untouched: `cycle_graph.py`, `agents/`, `tools/`,
  `cycle_budgets.py`, the runtime plan's invariants.
- `/api/*` keeps its contract — `scripts/cycle_e2e.py` is a customer of
  it, so is Mattermost.
- The wall stays fail-safe closed, `SWARM_AUTH_DISABLED=1` stays the
  test switch, `BASE_PATH` stays the prefix (`{{ base }}` on every link).
- No CDN, no runtime fetch of fonts or scripts; `app.css` generated,
  never committed.
- Any key an agent node returns is declared in `AgentState` — not
  touched here, repeated because every plan repeats it.
- A merge to main deploys and interrupts a running cycle; milestones
  merge when prod is idle (`cd.yml` waits up to 30 min). Docs-only
  merges do not deploy once #292 lands.

## Risks

- The theater (`v2/_stage.html`, 170 lines of polling, pinned issue,
  demo-pending) is the most intricate port; M4 keeps its stage
  endpoint and tests (`test_v2_theater*.py`) and changes the markup.
- The report store's `demo_report` shape feeds the player; M4 reads it,
  never rewrites it.
- Deleting V1 removes routes the harness or Mattermost might still name:
  M6 greps `scripts/`, `theswarm_common/` and the docs before each
  deletion, and the walk-through demo is the proof.
- Geist is loaded from Google Fonts on the prototype only; in the
  product both faces are vendored at M1 or the plan falls back to Plex
  Sans with the same tokens — the look is the tokens, not the face.
