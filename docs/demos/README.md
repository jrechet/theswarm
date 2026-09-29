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
| [`techlead-leaves-foreign-prs.webm`](techlead-leaves-foreign-prs.webm) | A real harness run (past-concerts-toggle, #434) with concert-tour-app#433 — a README note opened by hand on a `docs/` branch — open: the theater's feed, filtered to the TechLead, reads "PR #433: approved, not the swarm's — left for its author" next to "Merged: [439]"; #433 stays open for its author | `f211f5c2ccf1`, 2026-09-29 |
| [`v2-board-after-cleanup.webm`](v2-board-after-cleanup.webm) | The same board after `scripts/clean_stale_labels.py --close-before 2026-09-01 --apply`: 33 April–August issues closed as not planned, 10 back to ready, each with a comment — no Stalled group left | board only, 2026-09-29 |
| [`v2-cycle-fresh-database.webm`](v2-cycle-fresh-database.webm) | A real harness run (ical-feed, #426) — the "before": concert-tour-app#425 merged mid-cycle by the TechLead (the owner's choice), QA ran on a database of its own per server, and ten feature tests asked the *unseeded* E2E server for tour 1: a false "built but broken" and regression, which the swarm's PO diagnosed itself; `calendar.ics` was downloaded, not shown | `79e1658b2462`, 2026-09-29 |
| [`qa-seeded-e2e.webm`](qa-seeded-e2e.webm) | The "after", QA's real E2E step on the past-concerts-toggle PRs (#439–#441): the E2E server seeded like the demo servers, the file written from the seed's data — 15 `test_feature_*` tests passed, both behaviour gates pass | QA step only, 2026-09-29 |
| [`qa-triage.webm`](qa-triage.webm) | The triage, on the exact faulty assertion cycle `f211f5c2ccf1` wrote (planted, labelled): it fails against the real app, and one real Claude call reads the test and the templates — "a substring match that also catches concert-card-date … each of the 6 seeded cards is counted 4x … the app correctly renders 6 cards": the gate is inconclusive, the verdict unverified, not broken | QA step only, 2026-09-29 |
| [`qa-feature-pages.webm`](qa-feature-pages.webm) | QA's real captures on concert-tour-app at #393–#395, no cycle: the target's `demo.seed` fills its empty database, the walk reaches the pages the PRs added (`/api/v1/concerts/1/occupancy` 75 % sold, `/concerts/1/lineup`), the report's new `feature_pages` gate says pass (2 of 2 answered 2xx), the player says "not measured" and "N not run" instead of zeros and a green claim | capture-only, 2026-09-28 |
| [`v2-live-feed.webm`](v2-live-feed.webm) | A second real Play, "Tell a fan when the next concert is" (#397): the theater's Activity feed fills live — the Dev's steps and tool calls, PRs, reviews, "Memory compacted" — and the rail's last messages are sentences, not "]" | `57adc6cdea13`, 2026-09-28 |
| [`qa-legible-pages.webm`](qa-legible-pages.webm) | The same captures after the fix: both lanes side by side on a brand-new database (no first-boot DDL race — the video lane waits for the screenshot lane's server), and the feature's API pages drawn legible ("GET /api/v1/concerts/1/occupancy → 200" over the JSON, pretty-printed, large) — shown full size at the end | capture-only, 2026-09-28 |
| [`v2-theater-to-demo.webm`](v2-theater-to-demo.webm) | A real harness run (price-range, #411): the theater of the finished cycle ends on its demo — "The demo is ready · 3 PRs merged · 3/3 stories", the video, "Watch the demo →" — then the player and the reliability panel. It also shows, honestly, a false "built but broken" off a stale E2E test of the tours listing, which the next change fixes | `6186726707ca`, 2026-09-28 |
| [`v2-theater-after-restart.webm`](v2-theater-after-restart.webm) | A fresh server — the in-memory tracker has forgotten everything — and the finished country-stats cycle's theater is drawn from the database: stations done, the feed from the event store, the demo card from the report store, "Watch the demo" to the player | `7f4f2188cd90`, 2026-09-28 |
| [`demo-announced-on-issue.webm`](demo-announced-on-issue.webm) | The comment the swarm posts on the issue that asked for the feature, once its demo is ready — built from the stored report of `7f4f2188cd90`, rendered by GitHub's markdown API, posted nowhere (a laptop has no public link to give) | render only, 2026-09-28 |
| [`harness-feature-verdict.webm`](harness-feature-verdict.webm) | A real harness run (tour-revenue, #418) after the fix: QA rewrote its E2E file for the feature (six `test_feature_revenue_*` tests), the whole-API run still failed one unrelated test (`X-Total-Count` on the concerts listing — shown red on the gates slide), and the verdict read the feature: "PASS — behaviour verified on the running app", no false regression | `03790f693195`, 2026-09-28 |
| [`qa-fresh-database.webm`](qa-fresh-database.webm) | QA's real captures on concert-tour-app with its launch declared on `DATABASE_URL: sqlite:///{tmp}/demo.db` (concert-tour-app#425): every demo server gets a database of its own, the seed fills it, and the tour-revenue page reads **revenue 4,901,500.00 over 3 concerts** — the seeded tour — where the same demo had shown an E2E leftover at 0.00 | capture-only, 2026-09-28 |
| [`harness-sell-tickets.webm`](harness-sell-tickets.webm) | The first run of the topped-up manifest (sell-tickets, #442 → #443–#446): four PRs merged (#447–#450), story closed, and the verdict read off the feature's own tests — nine `test_feature_*` passed; `feature_pages` says "not run: the PRs add no GET route to walk", which is true of a POST-only feature: "PASS — behaviour verified on the running app", $2.21 in 19 min. The film also shows what is missing: the demo video and screenshots show the dashboard and the API root, nothing of selling a ticket | `68fd55bf81e5`, 2026-09-29 |
| [`techlead-reviews-once-per-head.webm`](techlead-reviews-once-per-head.webm) | A real harness run with the fix (lineup-add, #451 → PRs #455–#456, PASS, $2.67), its theater filmed afterwards with the feed filtered on the Tech Lead: "PR #307: REQUEST_CHANGES — unchanged since it was reviewed" and "PR #433: APPROVE — unchanged since it was reviewed" — no Claude call, no review, no comment. #307's head had not moved since 2026-09-24 and every cycle had reviewed it again (twelve identical REQUEST_CHANGES); the new PRs are reviewed and merged as before | `383c7f77d983`, 2026-09-29 |
| [`qa-feature-calls.webm`](qa-feature-calls.webm) | QA's real captures of sell-tickets (PRs #447–#450 on a fresh clone, no cycle) with the demo calls: one Claude call read the code and the seed and wrote three calls — "Before: 15000 tickets sold, 5000 remaining", `POST /api/v1/concerts/1/tickets {"quantity": 500}` → 200, "After: 15500 sold, 4500 remaining" — each played on the demo server's own database and drawn as request and answer, in the screenshots and the video. `feature_calls` passes where `feature_pages` could only say "not run" | capture-only, 2026-09-29 |
| [`harness-cancel-tour.webm`](harness-cancel-tour.webm) | #262 on a real cycle (cancel-tour, #457 → PRs #462–#464, #463 sent back once and fixed in the same cycle, PASS, $1.88): QA wrote six demo calls, played them in both lanes, all 200 — the video ends on "After: the tour now shows status 'cancelled'", story #460 carries its POST and PUT exchanges, and `feature_calls: pass — 2 of 2 call(s) of the feature answered 2xx` | `d119d706fbae`, 2026-09-29 |
| [`v2-breakdown-closed-is-done.webm`](v2-breakdown-closed-is-done.webm) | lineup-add's finished theater, redrawn with the fix: "3/3 done", #454 struck through like its siblings — it was closed "already satisfied" with no status label and read as unbuilt ("2/3 done") on a story that was closed | `383c7f77d983`, 2026-09-29 |
| [`report-repair-one-line.webm`](report-repair-one-line.webm) | The gates slide of cancel-tour's real report, before and after: a passing E2E gate carried pytest's whole setup excerpt (a dozen "ERROR at setup of …" blocks); the repair is now said in one line — "15 passed, 0 failed (file repaired once: TypeError: 'module' object is not callable)" | render only, `d119d706fbae`, 2026-09-29 |
| [`harness-month-stats.webm`](harness-month-stats.webm) | The first real run with the E2E fixture given in the prompt (month-stats, #471 → PRs #475–#477, PASS, $1.39): QA's file set up first time — `e2e_tests: 22 passed, 0 failed`, no repair — where the three runs before each needed one for "TypeError: 'module' object is not callable" at setup; the feature page (`/api/v1/stats/months`) answers 200 with the counts per month | `ed1aa4d9a9fd`, 2026-09-29 |
| [`claude-credentials-wall.webm`](claude-credentials-wall.webm) | Prod's incident of 2026-09-29 13:47 reproduced locally (an invalid OAuth token, no `~/.claude` session to fall back on): the harness's cycle dies in 10 s and is scored **not measured — interrupted**, with the way to renew the credentials, no regression, its story closed; `/health` says `claude: auth_expired` (a warning); a second harness run reads it and starts nothing — no issue, no cycle | local, no Claude spend, 2026-09-29 |
| [`sdk-token-fallback.webm`](sdk-token-fallback.webm) | One real SDK call with an invalid `CLAUDE_CODE_OAUTH_TOKEN` and a session on disk, before and after: the auth retry "without the token" used to send the same token (the SDK merges its env over the parent's) — the same 401 twice; now the dropped token is overridden to empty and the retry reaches the session on disk (its own answer: on this laptop, expired too — so the call ends on the credential wall, naming it) | local, 2026-09-29 |
| [`v2-board-old-ready-closed.webm`](v2-board-old-ready-closed.webm) | concert-tour-app's board after `scripts/clean_stale_labels.py --close-ready-before 2026-09-01 --apply` (owner, 2026-09-29): the 14 April/August dashboard tasks still `status:ready` (#146–#162, #173, #182–#184) are closed as not planned, each with a comment saying why and how to ask again — Ready holds only this month's tasks | board only, 2026-09-29 |
| [`qa-e2e-sign-off-cut.webm`](qa-e2e-sign-off-cut.webm) | price-stats' real QA log: the E2E file did not collect — the writer had signed off after the code ("Dima here — that's the full E2E suite …", `SyntaxError: invalid character '—'`) — and the repair's diff (#265) shows that line was all it removed; the extractor now cuts such a tail itself, never a syntax error inside the code | log + tests, `79f45fdaadb9`, 2026-09-29 |

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
