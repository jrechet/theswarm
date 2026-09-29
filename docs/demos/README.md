# TheSwarm — committed demo videos

Per the plan rule (§4 of [`theswarm-04.md`](../../theswarm-04.md)):

> Chaque nouvelle feature ships avec une démo vidéo commitée en
> `docs/demos/<feature>.webm` ou dans le store. Pas de démo = pas de merge.

## Index

| File | Sprint | Covers |
|------|--------|--------|
| [`sprint-A.webm`](sprint-A.webm) | A — Fondations démo push | F1 SSE toast + Mattermost DM, F2 before/after, F3 walkthrough video, F4 thumbnail + GIF |
| [`sprint-B.webm`](sprint-B.webm) | B — Controls in-dashboard | C1 config editor, C2 effort slider, C3 secret vault, C4 cost caps, C6 kill-switch |
| [`sprint-C.webm`](sprint-C.webm) | C — Approve/Reject inline + preview | F5 public demo URL, F6 inline approve/reject, F9 live preview iframe |
| [`sprint-D.webm`](sprint-D.webm) | D — Observabilité live & replay | V1 activity feed, V2 replay scrubber, V3 agent thoughts, V5 Web Push, C5 cost preview |
| [`sprint-E.webm`](sprint-E.webm) | E — Mémoire vivante & improver | M1 memory viewer, M2 retrospective, M4 Improver CLAUDE.md PR |
| [`sprint-F.webm`](sprint-F.webm) | F — Pluggabilité & polish | P1 webhook, P2 Linear adapter, M3 compaction, F7 speed, F8 comparator |
| [`sprint-G.webm`](sprint-G.webm) | G — Résilience & fail-safes | G1 checkpoints, G2 adaptive Claude, G3 GitHub breaker, G4 readiness, G5 resume UI |

## V2 — the product, filmed on real cycles

Recorded with [`scripts/record_v2_demo.py`](../../scripts/record_v2_demo.py):
a local server, a real repository, a real cycle on the subscription — the
browser does what the owner does. Each one names the cycle it filmed.

| File | Covers | Cycle |
|------|--------|-------|
| [`v2-play-to-demo.webm`](v2-play-to-demo.webm) | Pick `concert-tour-app` → write "Show how full a concert is" → the issue on the board (highlighted, #387) → ▶ Play → the theater live → 14 min later: 4/4 sub-tasks, PRs #392–#395 reviewed and merged → the latest-demo card → the player (stories, QA gates 325 unit / 36 E2E / 97.1 % coverage, screenshots, video) | `28371c2016da`, 2026-09-28, $2.11 |
| [`v2-board-truth.webm`](v2-board-truth.webm) | concert-tour-app's real board on a local server, no cycle: nothing running and no open PR for the "review" issues, so no Building and no In review — 39 issues labelled so by cycles long gone are Stalled, each still one Play away (the board used to read "Building 17") | board only, 2026-09-29 |

| [`qa-feature-pages.webm`](qa-feature-pages.webm) | QA's real captures on concert-tour-app at #393–#395, no cycle: the target's `demo.seed` fills its empty database, the walk reaches the pages the PRs added (`/api/v1/concerts/1/occupancy` 75 % sold, `/concerts/1/lineup`), the report's new `feature_pages` gate says pass (2 of 2 answered 2xx), the player says "not measured" and "N not run" instead of zeros and a green claim | capture-only, 2026-09-28 |
| [`v2-live-feed.webm`](v2-live-feed.webm) | A second real Play, "Tell a fan when the next concert is" (#397): the theater's Activity feed fills live — the Dev's steps and tool calls, PRs, reviews, "Memory compacted" — and the rail's last messages are sentences, not "]" | `57adc6cdea13`, 2026-09-28 |
| [`qa-legible-pages.webm`](qa-legible-pages.webm) | The same captures after the fix: both lanes side by side on a brand-new database (no first-boot DDL race — the video lane waits for the screenshot lane's server), and the feature's API pages drawn legible ("GET /api/v1/concerts/1/occupancy → 200" over the JSON, pretty-printed, large) — shown full size at the end | capture-only, 2026-09-28 |
| [`v2-theater-to-demo.webm`](v2-theater-to-demo.webm) | A real harness run (price-range, #411): the theater of the finished cycle ends on its demo — "The demo is ready · 3 PRs merged · 3/3 stories", the video, "Watch the demo →" — then the player and the reliability panel. It also shows, honestly, a false "built but broken" off a stale E2E test of the tours listing, which the next change fixes | `6186726707ca`, 2026-09-28 |
| [`v2-theater-after-restart.webm`](v2-theater-after-restart.webm) | A fresh server — the in-memory tracker has forgotten everything — and the finished country-stats cycle's theater is drawn from the database: stations done, the feed from the event store, the demo card from the report store, "Watch the demo" to the player | `7f4f2188cd90`, 2026-09-28 |
| [`demo-announced-on-issue.webm`](demo-announced-on-issue.webm) | The comment the swarm posts on the issue that asked for the feature, once its demo is ready — built from the stored report of `7f4f2188cd90`, rendered by GitHub's markdown API, posted nowhere (a laptop has no public link to give) | render only, 2026-09-28 |
| [`harness-feature-verdict.webm`](harness-feature-verdict.webm) | A real harness run (tour-revenue, #418) after the fix: QA rewrote its E2E file for the feature (six `test_feature_revenue_*` tests), the whole-API run still failed one unrelated test (`X-Total-Count` on the concerts listing — shown red on the gates slide), and the verdict read the feature: "PASS — behaviour verified on the running app", no false regression | `03790f693195`, 2026-09-28 |
| [`qa-fresh-database.webm`](qa-fresh-database.webm) | QA's real captures on concert-tour-app with its launch declared on `DATABASE_URL: sqlite:///{tmp}/demo.db` (concert-tour-app#425): every demo server gets a database of its own, the seed fills it, and the tour-revenue page reads **revenue 4,901,500.00 over 3 concerts** — the seeded tour — where the same demo had shown an E2E leftover at 0.00 | capture-only, 2026-09-28 |

```bash
# QA's captures on a local checkout of the target, then the player (no cycle)
uv run python scripts/record_qa_demo.py --repo jrechet/concert-tour-app \
    --workspace <checkout> --prs <PR numbers> --name <name>
# a filmed Play (writes docs/demos/<name>.webm)
uv run python scripts/record_v2_demo.py --repo jrechet/concert-tour-app \
    --name <name> --feature "<issue title>" --body "<issue body>"
# the eval harness instead of the filmed Play, then what it judged
uv run python scripts/record_v2_demo.py --repo jrechet/concert-tour-app \
    --name <name> --harness-feature <eval feature id>
```

## Recording / re-recording a walkthrough

Every sprint demo is a real Playwright capture of the dashboard tour, with
the per-sprint demo play page included in the stops. To re-record:

```bash
# one sprint
uv run python scripts/record_sprint_walkthrough.py B

# all of B-F in sequence
uv run python scripts/record_sprint_walkthrough.py all
```

The script boots an isolated TheSwarm server in a temp dir, runs `seed_self`
(so the full sprint history is populated), walks the key dashboard screens
and writes `docs/demos/sprint-<L>.webm`.

On deploy, the unified server runs `seed_self` at startup and copies the
committed webms into the artifact store, so every dashboard gets the
current recordings automatically. Set `SWARM_SKIP_SELF_SEED=1` to opt out.
