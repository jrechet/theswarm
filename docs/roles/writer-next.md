# Technical Writer — NEW role

> Codenamed (e.g., `Sol`, `Vera`, `Kai`). Per project.

## Why this role

Docs rot silently. Dev writes READMEs as an afterthought. API docs lag. Users open issues that were answered in the changelog they never read. Writer owns **externally-facing explanation** so engineers can stay heads-down.

## Responsibilities

### 1. README + quickstart

- Enforces a project README skeleton (what / why / install / quickstart / links). Updates on structural changes.
- Quickstart is executable: Writer runs the quickstart from scratch in a clean container each cycle; if it breaks, opens a `docs:rot` issue.

### 2. API reference

- Auto-generates from OpenAPI / typedoc / pydoc-markdown when available.
- Hand-writes intros and examples for each endpoint; these intros are the bit that matters.

### 3. Changelog & release notes

- Generates a human-readable changelog from merged PRs (partners with Release Manager).
- Release notes with "what's new, what broke, what to migrate".

### 4. User guides & tutorials

- PO-driven priorities: most-used flows get tutorials.
- Tutorials get E2E-tested (QA cooperates) so they never drift.

### 5. Inline-docs hygiene

- Enforces global rule "no comments unless non-obvious WHY". Strips drift; pushes context into ADRs or user-facing docs where it belongs.

### 6. Voice & style

- Maintains a `style-guide.md` (tone, reading-level target, do/don't list).
- Dashboard has a "rewrite in project voice" action for any docs PR.

## Interactions

- **← Dev / TechLead.** Hooks on PR events: if docs/ wasn't touched but user-visible change, Writer files a follow-up.
- **← Release Manager.** Receives release cut; writes notes.
- **→ PO.** Surfaces docs gaps as stories.

## Memory patterns

- Per-project-per-Writer: `style_guide`, `docs_map`, `tutorial_index`, `rot_log`.

## Dashboard surfaces

- **Docs health** panel per project (coverage, rot signals, last-reviewed).
- **Changelog** stream.
- **Writing queue** (items awaiting a writer pass).

## New tools

| Tool | Purpose |
|---|---|
| `article-writing` skill | Already available |
| Markdown linters (`markdownlint`) | Hygiene |
| `vale` | Style enforcement |
| Container runner | Quickstart verification |

## Success metrics

- README freshness: last updated within 30 days OR no structural change detected.
- Quickstart pass rate: 100% across cycles.
- Docs coverage (endpoints with descriptions) ≥ 90%.

## Rollout

1. **Foundation.** Codename, style guide template, README skeleton check.
2. **Changelog + release-notes generator.**
3. **Quickstart verification.**
4. **Tutorials as E2E tests.**
5. **Style linting on docs PRs.**
