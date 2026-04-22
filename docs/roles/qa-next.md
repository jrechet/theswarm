# QA — Next

> Each QA instance has a codename (e.g., `Aya`, `Diego`, `Shiro`). Memory keyed by codename.

## Today

- 10-node pipeline: context → E2E writing → unit/E2E/security runs → screenshots → videos → demo report.
- Uses Playwright (screenshots, videos), `semgrep` for security, `pytest --cov`.
- Artifacts stored via `LocalArtifactStore`; surfaced in `/reports/{id}` and demo player.

## Gaps

- **Happy-path bias.** E2E tests are generated from stories; rarely cover failure, auth, empty-state, i18n, slow-network.
- **Flaky tests silent.** No quarantine, no retry-with-reason, no flake score.
- **No performance signal.** Doesn't run Lighthouse / CWV / k6 against the touched surface.
- **No accessibility signal.** No a11y audit (axe).
- **No regression guard.** Each cycle writes fresh E2E; tests aren't promoted to a persistent suite with coverage-of-flows.
- **Security check is one-shot semgrep.** No SCA (SBOM), no secret scan, no license audit.
- **Demo artifacts are generic.** Always same framing; no project-aware story-telling.

## Next responsibilities

### 1. Coverage strategy by test archetype

Per-story test mix chosen intentionally:
- **Unit** (always): pure logic, boundary cases.
- **Integration** (when touching persistence / external APIs): real DB, record & replay HTTP with `respx` / MSW.
- **E2E** happy path + at least one: empty state, auth failure, slow-network (throttled), small viewport (≤ 375 px).
- **Visual regression** (when UI touched): Playwright snapshot diff, masked dynamic regions.
- **Accessibility**: axe-core pass, WCAG AA as floor.
- **Performance**: Lighthouse CI for web; k6 smoke for APIs (RPS / p95 target from project config).
- **Security**: semgrep + `gitleaks` (secrets) + SCA (`osv-scanner`) + license audit on build artifact.

### 2. Persistent regression suite

- All E2E / visual tests promoted to `tests/e2e/regression/` after first successful run.
- Nightly regression job (separate from cycle) runs the whole suite against `main`.
- Failures open `qa:regression` issues, trigger a hot-fix cycle.

### 3. Flake hygiene

- **Retry policy** with reason capture: flake is retried up to N times; each retry logs what changed (timing, assertion message, DOM diff).
- **Quarantine** on persistent flake; file a `qa:flake` issue; test stays running but doesn't block cycles.
- **Flake score** per test: `flakes / runs` over last 30 days, visible on dashboard. Tests above threshold auto-quarantined.

### 4. Richer demo artifacts

- **Narrated walkthrough.** QA assembles a per-story short video with captions ("Given X, user does Y, sees Z"). Already scaffolded in F3; enrich with captions and acceptance-criteria overlay.
- **Before/after split view** (already F2). Enrich with a focus crop around the changed region.
- **Story outcome card**: one slide with acceptance criteria checked ✓ / ✗, metric moved.
- **Failure storyboard** for red stories (what broke, where, suggested fix).

### 5. Post-deploy verification

When the project has a deployed preview (Vercel / Fly / Docker Swarm on `jrec.fr` / custom):
- Run the full E2E suite against the live preview URL, not just local.
- Record real Lighthouse scores on the preview.

### 6. Test intelligence feedback

- Flag tests that only assert "no error" (low signal) — bounces them back to Dev.
- Flag tests that always pass regardless of implementation (via mutation testing sample, `mutmut` / `stryker`, run on a budget).
- Detect coverage gaps in critical files and propose stories to TechLead.

### 7. Synthetic users

- Generate realistic fixtures (names, emails, locales, edge unicode) instead of `test@test.com` everywhere.
- Multi-locale run for stories flagged as user-visible text changes.

## New tools

| Tool | Purpose |
|---|---|
| axe-core / `@axe-core/playwright` | Accessibility audit |
| Lighthouse CI | Performance |
| k6 | API load smoke |
| `gitleaks` | Secret scan |
| `osv-scanner` | SCA |
| Mutation testing (sampled) | Test-quality check |
| Visual diff (Playwright snapshots or `pixelmatch`) | Visual regression |

## Memory patterns

- **Per-project-per-QA memory** `(project_id, codename)`:
  - `test_patterns` — working selectors, auth fixtures, page-object snippets specific to this project.
  - `flakes` — history with root causes.
  - `gaps` — known uncovered flows.
  - `perf_baselines` — Lighthouse/k6 baselines per route.
  - `a11y_violations` — open vs. resolved by path.
- Global: `cross_project/test_archetypes`.

## Dashboard surfaces

- **Test health** panel: pass rate, flake score, coverage trend, perf trend, a11y violation count.
- **Demo comparator** (already F2). Add regression diff from last cycle.
- **Quarantine list** with "unquarantine" action (with mandatory justification).
- **Security posture** card: open CVEs, secret findings, license issues.

## Success metrics

- Flake rate < 2% over 30 days.
- Regression suite duration ≤ 10 min (budget the growth).
- A11y serious+critical violations = 0 on ship.
- Lighthouse perf ≥ 80 on LCP / INP / CLS on demo preview.
- Coverage of critical paths ≥ 90%.

## Rollout

1. **Foundation.** Codename, per-project memory, test archetype mix, flake retry + quarantine.
2. **Regression suite promotion + nightly job.**
3. **A11y + perf + SCA + secret scan** added to quality gates.
4. **Richer demo artifacts** (narrated walkthrough, outcome cards).
5. **Mutation testing (sampled) + test intelligence feedback.**
