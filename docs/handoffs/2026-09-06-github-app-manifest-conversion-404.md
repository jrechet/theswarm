# Handoff — GitHub App manifest conversion returns 404

**Date:** 2026-09-06 · **Status:** BLOCKED, unresolved · **Owner:** jrechet
**Blocks:** "Sign in with GitHub" and the repo picker fed by the App installation.
Until the App exists, `/` lists only the three legacy V1-registered projects
(`concert-tour-app` 2026-04-21, `rssj` 2026-05-05, `theswarm` 2026-09-01) and
the login page hides the GitHub button on purpose.

Read this whole file before touching anything: the previous agent burned
several hours re-deriving facts that are established below.

---

## 1. What is built and live (do not rebuild)

All merged to `main` and deployed on `https://bots.jrec.fr/swarm`:

| PR | What |
|---|---|
| #39 | Auth wall, fail-safe closed; `/login` with access key; `Bearer <key>` on `/api/*` |
| #40 | GitHub App: manifest-flow setup page, installation tokens, OAuth login (owner-only) |
| #41 | V2 UI (`templates/v2/`, Tailwind standalone, Plex vendored): `/` picker, repo page, composer, ▶ Play |
| #42 | The theater `/c/{cycle_id}` (four-agent rail, pinned issue breakdown, feed, per-agent filter) |

The whole product flow works end to end **except** the App creation step.
Plan: `docs/plans/2026-09-v2-one-flow.md`. Dependency map: `docs/DEPENDENCIES.md`.

**Code of interest**
- `src/theswarm/presentation/web/routes/github_setup.py` — `build_manifest()`, `GET /setup/github-app` (form that POSTs the manifest to GitHub), `GET /setup/github-app/callback` (exchanges `?code=` via `POST https://api.github.com/app-manifest/{code}/conversions`, stores creds in the Fernet vault).
- `src/theswarm/tools/github_app.py` — credentials (vault + env fallback), RS256 app JWT, 1 h installation tokens, `ensure_github_token()`.
- `src/theswarm/presentation/web/templates/github_app_setup.html` — the form + a tiny inline script that injects the user-chosen app name into the manifest JSON on submit.
- Tests: `tests/presentation/test_github_setup.py` (13), `tests/test_github_app.py` (10).

---

## 2. The bug — exact reproduction (owner did it 4×, screenshots seen)

1. `https://bots.jrec.fr/swarm/setup/github-app` → click **Create the app on GitHub**.
2. Browser lands on **`https://github.com/settings/apps/manifest`** — GitHub's *minimal* manifest page: one field "GitHub App name = theswarm-jrec" and a green button **"Create GitHub App for jrechet"**. (No permissions review page — that is normal for the manifest flow.)
3. Owner clicks the green button.
4. GitHub redirects to **`https://bots.jrec.fr/swarm/setup/github-app/callback?code=<40 hex>`** — **only** `code`, no `state`, no `installation_id`.
5. Our callback POSTs `https://api.github.com/app-manifest/<code>/conversions` → **`404 {"message":"Not Found"}`** → we render the setup page with the error banner, status 502.
6. **`https://github.com/settings/apps` shows "No GitHub Apps"** afterwards. Nothing was created.

Codes observed (all 40-hex, all 404): `6ef09657…`, `51d36119…`, `1f54da05…`, `5dec24dd…`.
Two of the attempts were 10 s apart, so this is not a stale-code problem.

---

## 3. Facts established (each one verified — do not re-verify)

1. **The served manifest is valid JSON** with exactly these fields
   (fetched live from prod and `json.loads`-ed):
   `name`, `url=https://bots.jrec.fr/swarm`, `public=false`,
   `redirect_url=…/setup/github-app/callback`, `callback_urls=[…/auth/github/callback]`,
   `hook_attributes={url: …/webhooks/github, active: false}`,
   `default_permissions={contents:write, issues:write, pull_requests:write, checks:write, metadata:read}`,
   `default_events=[]`.
2. **The callback is hit exactly once per attempt** (uvicorn access log) — the code is not being consumed twice.
3. **Not a timing / race / server-IP problem**: a *fresh* code (seconds old) exchanged from a completely independent client (`gh api -X POST /app-manifest/<code>/conversions` on the developer's laptop) also returns the identical 404. A made-up code returns the identical 404. So GitHub simply does not know the code.
4. **No CSP / `form-action` header** on our pages — the browser may POST to github.com.
5. **No residual OAuth flow** that could inject a foreign `code`: grep for `login/oauth/authorize` / `swarm-bots` finds only a commit-trailer email and a log channel name. (The owner has an old OAuth App named `swarm-bots` in *OAuth Apps*; unrelated as far as the code shows.)
6. The conversion request is textbook (unauthenticated POST, `Accept: application/vnd.github+json`, `timeout=20`). Response body is GitHub's generic 404.
7. `https://github.com/apps/theswarm-jrec` → 404, **but this is inconclusive**: that page 404s for free names *and* for private apps alike.
8. Vault is empty (`/setup/github-app` still shows the create form; `load_credentials()` → None).

Net: GitHub shows the confirmation, the owner confirms, GitHub redirects with a
code, yet **no app persists and the code references nothing**. Everything on
our side up to the POST-to-GitHub is correct.

---

## 4. Hypotheses not yet tested — in the order to try them

1. **Globally-unique App name collision.** GitHub App names are unique across
   *all of GitHub*, not per account. If `theswarm-jrec` belongs to someone
   else (private → invisible to us), creation may fail after the confirm click
   while GitHub still bounces to `redirect_url` with a dead code.
   → In `github_setup.py`, make `DEFAULT_APP_NAME` unique (e.g. append 6 random
   chars) or just have the owner type `theswarm-jrec-<something random>` in the
   name field (it is editable on our page). **Cheapest test; do it first.**
2. **A manifest field rejected at persist time.** Try the *minimal* manifest:
   `name`, `url`, `redirect_url`, `public:false`, `default_permissions:{metadata:read}`;
   drop `hook_attributes`, `callback_urls`, `checks`, `default_events`. If it
   works, bisect fields back in. Prime suspects: `hook_attributes` with a URL
   but `active:false`; `checks:write`.
3. **Add `?state=`** to the form action (docs recommend it) and confirm it
   round-trips in the redirect — if it does not come back, GitHub is not
   treating our POST as a proper manifest submission.
4. **Browser side.** Retry in a private window / another browser to rule out
   an extension prefetching the callback URL (that would burn the code before
   the real navigation — though it does not explain why no app persists).
5. **Look right after the green click**: open `github.com/settings/apps` in a
   second tab immediately after clicking, to see whether an app exists
   momentarily and disappears.
6. If everything above fails, log GitHub's `x-github-request-id` from the 404
   response and open a GitHub support ticket — at that point it is their side.

---

## 5. Also fix while you are there

- The error banner says "expires after one hour and burns on first use" —
  misleading for an immediate 404. Show GitHub's real status + message.
- On conversion failure the page renders with `creds=None` **without re-reading
  the vault**; if a previous conversion had succeeded it would hide it. Re-load
  credentials before rendering the error.
- Log `dict(request.query_params)` in the callback so the next occurrence is
  fully traced without asking the owner for the URL bar.

---

## 6. Fallback if the manifest flow stays broken (owner decision, not yours)

A fine-grained Personal Access Token scoped to the chosen repos, pasted by the
owner into a settings page and stored in the existing Fernet vault, would
unblock repo listing / issue creation / cycles today — but loses the
"Sign in with GitHub" OAuth (only the App provides the OAuth client). Per the
owner's rules any new dependency/credential path is a shared decision: propose,
do not implement silently.

---

## 7. Operating the environment

- Prod: `https://bots.jrec.fr/swarm` (auth wall). Access key on the server:
  `ssh -p5422 debian@jrec.fr cat swarm-access-key.txt`. Never paste it in chat.
- Logs: `ssh -p5422 debian@jrec.fr 'docker service logs theswarm_theswarm --tail 2000'`
  (filter `setup/github-app|manifest`), or Seq at `logs.jrec.fr`.
  A `--follow` tail through a sandboxed background task fails — run it foreground
  or poll after the owner's attempt.
- Deploy: branch → PR → CI (~9 min) → `gh pr merge --squash` (auto-merge is
  disabled on the repo) → deploy lands when the service image tag equals the
  main SHA; expect a ~2 min 404 window during the rolling update.
- Tests: `uv run pytest tests/ -q --ignore=tests/e2e -p no:playwright`
  (2363 green as of #42); e2e smoke: `tests/e2e/test_dashboard_e2e.py::TestRouteSmokeWalk`.
- Owner GitHub login: `jrechet` (`SWARM_OWNER_LOGIN`). The owner already
  confirmed: GitHub App yes, single-user for now, public product later.
