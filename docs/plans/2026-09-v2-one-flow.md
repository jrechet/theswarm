# V2 — one flow, one screen at a time (2026-09)

Decision (owner, 2026-09-01): the V1 UI stays as-is; V2 is a fresh surface
focused on a single flow, GitHub-native. Single user for now; public product
is a later phase (execution isolation + billing are the gate, see the
product note "La porte d'entrée").

**The flow**: sign in with GitHub → my repos → pick one → write what I want
(creates a GitHub issue) → the issue appears on the board → ▶ Play →
a visual, live "theater" of the four agents building it.

## Étapes (each lands as its own PR, deployed and verified in prod)

0. **The lock** — issue #38. Signed-session auth wall, fail-safe closed,
   access-key login. `SWARM_ACCESS_KEY` / `SWARM_SESSION_SECRET` via repo
   secrets → write-env → `.env`. Key readable on the server:
   `~/swarm-access-key.txt`.
1. **GitHub App** — created via the manifest flow (owner clicks Create +
   Install; credentials go GitHub → server vault directly). Installation
   tokens (1 h) replace the static `GITHUB_TOKEN`; "Sign in with GitHub"
   (App OAuth, owner-only allowlist) joins the access key. New lib: PyJWT.
2. **V2 shell** — `templates/v2/`, Tailwind v4 standalone binary at Docker
   build (no node, no CDN), IBM Plex vendored. `/` = repo picker fed by the
   App installation; picking a repo auto-registers the project.
3. **Composer + board** — big "what should we build" box → creates the GH
   issue → appears below with ▶ Play → targeted cycle (existing #25 flow).
4. **The theater** — live cycle page: four agent stations on a progress
   rail (SSE), the issue + its breakdown, activity feed; click an agent →
   its log panel (deeper log UX is its own later feature).

## Non-goals for now

- Multi-user / multi-tenant (needs per-cycle execution isolation)
- Webhook-triggered cycles, PR-comment loop (after the App exists they get
  cheap — tracked as follow-ups)
- Deleting anything from V1
