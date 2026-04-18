# TheSwarm — Improvement Plan: Final Report

**Date:** 2026-04-17
**Branch:** `main`
**Scope:** P0–P3 (15 tasks, #22–#36) — dashboard 100% feature-complete with comprehensive test coverage
**Status:** ✅ All 15 tasks complete · 1085 tests passing (was 1067 before this session; +18 net)

---

## P0 — Block-merge gates (done)

| # | Task | Notes |
|---|------|-------|
| 22 | P0.1 Player E2E (prev/next, slides, artifacts) | Playwright journey in `tests/e2e/test_dashboard_e2e.py` |
| 23 | P0.2 Fragments E2E | HTMX round-trip coverage |
| 24 | P0.3 API E2E exhaustive | Every `/api/v1/*` endpoint covered |
| 25 | P0.4 CI gate non-skippable smoke walk | `e2e-smoke` job in `.github/workflows/ci.yml`; `deploy` now needs `[tests, e2e-smoke]` |
| 26 | P0.5 Partial-data report tests | Reports render with missing video / screenshots / gates |

**Outcome:** No PR can deploy without passing a real Chromium walk of the dashboard.

---

## P1 — Dev ergonomics & operational hygiene (done)

| # | Task | Notes |
|---|------|-------|
| 27 | P1.6 `theswarm dev-seed` command | `src/theswarm/application/services/dev_seed.py` + CLI handler. 7 tests. |
| 28 | P1.7 Demo video E2E roundtrip | 4 Playwright tests verify `<video>` element and `video/webm` serving. Test server takes an `artifact_dir` kwarg so tests never pollute `~/.swarm-data/`. |
| 29 | P1.8 Artifact GC command | `src/theswarm/application/services/artifact_gc.py` + CLI. Dry-run by default. 8 tests. |
| 30 | P1.9 `/health` strict ok/warn/error | Tri-state: `ok`, `warn`, `error` (HTTP 503 on DB failure). 4 tests. |

---

## P2 — UX polish (done)

| # | Task | Notes |
|---|------|-------|
| 31 | P2.10 Demos filtering by project/date | `/demos/?project=&since=YYYY-MM-DD`. Filter form in header. 6 tests. |
| 32 | P2.11 Project detail demos link | "View demos" button on `/projects/<id>` → `/demos/?project=<id>`. 1 test. |
| 33 | P2.12 Demo card thumbnail preview | `DemoReport.thumbnail_path` property + `<img>` on demo cards. 4 tests. |
| 34 | P2.13 Cycle timeline view | Gantt-style proportional bars, phase start times, per-phase duration labels. Added `duration_seconds` + `start_time_display` to both `PhaseExecution` and `PhaseDTO`. 3 tests. |

---

## P3 — Observability (done)

| # | Task | Notes |
|---|------|-------|
| 35 | P3.14 `/metrics` Prometheus endpoint | `src/theswarm/presentation/web/routes/metrics.py` exposes `theswarm_uptime_seconds`, `theswarm_projects_total`, `theswarm_cycles{status=…}`, `theswarm_cycle_cost_usd_sum`, `theswarm_cycle_tokens_sum`. 2 tests. |
| 36 | P3.15 SVG mini-charts on dashboard | New `partials/_sparkline.html` renders inline SVG sparklines in "Cost 7d" and "Cycles 7d" stat boxes. `DashboardDTO.cost_per_day_7d` and `cycles_per_day_7d` tuples populated in `GetDashboardQuery`. 2 tests. |

---

## Media inventory

### Current screenshots (refreshed for this session's work)

- [`demo-dashboard.png`](./demo-dashboard.png) — Dashboard with SVG sparklines under "Cost 7d" and "Cycles 7d" (P3.15)
- [`demo-demos.png`](./demo-demos.png) — Demos browse with project/since filter form (P2.10) and card thumbnails (P2.12)
- [`demo-health.png`](./demo-health.png) — `/health` returning `status: "warn"` tri-state when chat integration is missing (P1.9)
- [`demo-metrics.png`](./demo-metrics.png) — `/metrics` Prometheus text output: uptime, projects, cycles by status, cost/tokens (P3.14)

### Other screenshots (still current, unchanged this session)

- [`dashboard-with-data.png`](./dashboard-with-data.png) — Dashboard populated via `dev-seed`
- [`demo-projects.png`](./demo-projects.png) — Projects list
- [`demo-cycles.png`](./demo-cycles.png) — Cycles list
- [`demo-features.png`](./demo-features.png) — `/features/` landing
- [`demo-api-features.png`](./demo-api-features.png) — API docs surface

### Regenerate demo videos

```bash
uv run python -m theswarm serve            # start server on :8091
uv run python -m theswarm dev-seed --count 5 --reset
uv run python -m theswarm record-demos     # writes .webm into ~/.swarm-data/artifacts/feature-demos/
open http://localhost:8091/demos/          # play them back
```

No committed `.webm` videos yet. The `TestDemoVideoRoundtrip` E2E class generates an in-memory WebM blob per run and verifies the dashboard serves it. To get a *real* walkthrough video, run `record-demos` as above.

### Artifact lifecycle

- New artifacts land under `~/.swarm-data/artifacts/{cycle_id}/{screenshot|video|diff|log}/`.
- Run `uv run python -m theswarm artifact-gc` to list orphans (dirs with no matching `reports` row) and `--apply` to delete.

---

## New files

| Path | Purpose |
|------|---------|
| `src/theswarm/application/services/dev_seed.py` | Synthetic demo seeding |
| `src/theswarm/application/services/artifact_gc.py` | Orphan artifact GC |
| `src/theswarm/presentation/web/routes/metrics.py` | `/metrics` endpoint |
| `src/theswarm/presentation/web/templates/partials/_sparkline.html` | Reusable SVG sparkline |
| `tests/application/test_artifact_gc.py` | GC service tests |
| `tests/presentation/test_demos_routes.py` | `/demos/` filter + thumbnail tests |

## Notable modified files

- `.github/workflows/ci.yml` — E2E smoke gate
- `src/theswarm/domain/reporting/entities.py` — `DemoReport.thumbnail_path`
- `src/theswarm/domain/cycles/entities.py` — `PhaseExecution.duration_seconds`, `start_time_display`
- `src/theswarm/application/dto.py` — `PhaseDTO.duration_seconds`, `DashboardDTO.cost_per_day_7d`, `cycles_per_day_7d`
- `src/theswarm/application/queries/get_dashboard.py` — 7-bin histogram
- `src/theswarm/presentation/web/routes/health.py` — tri-state + HTTP 503
- `src/theswarm/presentation/web/routes/demos.py` — query-param filtering
- `src/theswarm/presentation/web/server.py` — `artifact_dir` kwarg
- `src/theswarm/presentation/web/templates/*` — filter form, thumbnail, timeline bar, sparklines
- `src/theswarm/presentation/web/static/css/dashboard.css` — styles for all new UI
- `src/theswarm/presentation/cli/main.py` — `dev-seed`, `artifact-gc` subcommands

---

## Test suite status

```
1085 passed, 3 warnings in 5.77s   (full suite minus E2E)
```

Plus `TestDemoVideoRoundtrip` E2E (4/4) on Chromium.

---

## Suggested next steps

1. **Capture refreshed screenshots + walkthrough video** — now that filters, thumbnails, timeline, and sparklines are live, re-run `record-demos` and commit the new media under `docs/` (not repo root) for cleaner PR reviews.
2. **Wire `/metrics` into Grafana/Prometheus** — scraping config lives outside this repo, but the contract is stable.
3. **Hook `artifact-gc --apply` into a daily cron** — prevents unbounded disk growth in long-running installs.
