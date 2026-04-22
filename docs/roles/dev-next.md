# Dev — Next

> Each Dev instance gets a codename (e.g., `Nora`, `Kenji`, `Tariq`). Memory and activity feed are keyed by codename.

## Today

- Graph: `pick_task → implement → quality_gates → (ralph-loop retry) → open_pr`. Max 2 retries.
- Claude generates full-file diffs via `---FILE:` blocks; runs `pytest`; opens a PR.
- Reads role-filtered memory (`conventions`, `stack`, `errors`).

## Gaps

- **No repo exploration before coding.** Dev implements against an abstract context without grep/glob of the area.
- **No test-first discipline.** Tests are co-authored with code; the TDD loop isn't enforced.
- **No local reproduction loop for failures.** Failed tests produce raw output; Dev doesn't parse, localize, and target.
- **No incremental diff / refactor preflight.** Large rewrites ship silently; no protection against unintended deletions.
- **No reuse search.** Writes new utilities instead of finding existing ones (contradicts global rule "search-first").
- **Blind to runtime.** No ability to actually run the app, hit an endpoint, check logs before handing off to QA.
- **No pair/review loop inside Dev.** Gets TechLead review after PR only; no self-review step.

## Next responsibilities

### 1. Research-before-code

- **Step 0: explore.** `Grep` / `Glob` the area of change, read nearest sibling files, summarize in-memory before any edit. Results logged to the agent thoughts stream for dashboard visibility.
- **Reuse search.** `gh search code` + local similarity search against utilities to see if the needed primitive already exists.
- **Library check.** `docs-lookup` / Context7 before adopting a new API.

### 2. Proper TDD loop

- **Write the test(s) first**, commit them to a throwaway branch, then run them to confirm RED.
- **Write minimal implementation** to GREEN.
- **Refactor** under green tests.
- Coverage delta reported on the PR. Coverage < 80% on changed lines blocks merge (configurable per project).

### 3. Targeted failure analysis

- Parse `pytest` / `jest` / `vitest` output into structured `FailedTest` objects. Rank by locality.
- Run only the failing test in a tight loop during debug (speed).
- When stuck after N iterations, open a `help-needed` note to TechLead memory instead of retrying blindly.

### 4. Safe diffs

- **Refactor preflight.** Before a diff that deletes ≥ 20 lines, Dev must list the callers and confirm they're migrated or untouched. Bails if uncertain.
- **Comment discipline.** Follows global `"no comments unless non-obvious WHY"` rule; lint for violations in self-review step.
- **Formatter + linter pass.** Auto-run project formatter/linter; retry up to 2× on auto-fixable issues.

### 5. Self-review step

- Before opening the PR, Dev runs an internal code-review prompt against the diff (different temperature, stricter rubric). Findings that are HIGH must be addressed or explicitly waived with rationale.
- Dev writes a PR description using a template: *Problem → Approach → Out of scope → Test plan → Risk*.

### 6. Runtime awareness

- When the project has a `dev:up` command (discoverable via project config): boot the app, exercise the change with a minimal smoke test, capture a screenshot or a log excerpt for the PR body.
- Surfaces errors to TechLead and QA with reproduction steps already included.

### 7. Incremental implementation

- For tasks estimated L/XL by TechLead: Dev proposes a split into sub-commits; ships the first, waits for partial review before continuing.

### 8. Live pair with humans

- Dashboard "nudge" channel: humans can leave a note on a running Dev task; the note is injected at the next tick of the implement loop.

## New tools

| Tool | Purpose |
|---|---|
| `Grep`/`Glob` already available | Repo exploration |
| `docs-lookup` skill | Library API confirmation |
| `search-first` skill | Reuse and library discovery |
| Coverage delta (`coverage.py xml` / `lcov`) | Changed-lines coverage |
| Project-configured formatter/linter (`ruff`, `prettier`, `eslint`, ...) | Auto-fix pass |
| `dev:up` command runner with log capture | Runtime smoke |

## Memory patterns

- **Per-project-per-Dev memory** `(project_id, codename)`:
  - `conventions` — project-specific idioms learned from reviews.
  - `stack` — tooling snapshot used by this project.
  - `pitfalls` — stack traces + fixes seen before, to dodge them earlier.
  - `helpers` — local utilities already in the repo worth reusing.
- Global: `cross_project/coding_patterns`.

## Dashboard surfaces

- **Dev timeline** per codename: tasks picked, time to PR, retries used, self-review score.
- **Task log** with live thoughts stream: exploration, test runs, retries.
- **Coverage delta per PR**.
- **Nudge** textbox live on any running Dev task.

## Success metrics

- PR acceptance rate (APPROVE w/o changes on first pass) ≥ 60%.
- Retries per task (median) ≤ 1.
- Changed-lines coverage ≥ 80%.
- % of diffs that delete >20 lines and triggered a refactor-preflight note: visible and monotonically improving.

## Rollout

1. **Foundation.** Codename, per-project memory, research-before-code step, reuse search.
2. **TDD enforcement.** RED → GREEN gate for new files; coverage delta on PRs.
3. **Self-review step + PR template.**
4. **Refactor preflight + nudge channel.**
5. **Runtime smoke tests** when `dev:up` is configured.
