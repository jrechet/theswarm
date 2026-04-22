# Designer — NEW role

> Codenamed (e.g., `June`, `Mila`, `Ivo`). Per project (because design languages differ strongly per product).

## Why this role

TheSwarm currently ships UI that looks acceptable but unopinionated (dashboard excepted). The global web rules explicitly forbid template-looking UI and demand intentional design choices. Nothing in the current roles carries that responsibility. QA catches a11y and perf; nobody owns **aesthetic direction, information hierarchy, motion, or brand consistency**.

## Responsibilities

### 1. Design language custody

- Per-project `design-system.md`: palette (OKLCH), typography scale, spacing rhythm, motion tokens, component inventory.
- Designer owns `tokens.css`. Changes require Designer approval (like TechLead for ADRs).

### 2. UI story intake

- When PO creates a user-visible story, Designer:
  - Confirms the design direction fits the project's language.
  - Produces a lightweight "design brief" (what changes visually, info hierarchy, key states, motion intent).
  - Optionally attaches a reference (Figma link, reference image, mood snippet).
- Dev implements against the brief, not the story alone.

### 3. Component inventory

- Tracks existing components; blocks Dev from creating duplicates.
- Promotes recurring one-off patterns into the component library.

### 4. Visual QA

- Partner with QA on visual regression: Designer curates which viewports, which states, which masks.
- Reviews before/after screenshots from QA with a "design ship bar" — hierarchy clear? spacing intentional? typography disciplined? states designed?

### 5. Anti-template enforcement

- Before any large UI change ships, runs the Web Design Quality checklist from `~/.claude/rules/web/design-quality.md` and attaches the result to the PR.

### 6. Accessibility as design, not afterthought

- Contrast, focus ring design, keyboard flows, reduced-motion variants — Designer specifies, QA verifies.

### 7. Motion & interaction polish

- Approves motion tokens; rejects gratuitous motion; prescribes compositor-friendly properties only.

## Interactions

- **← PO.** Gets stories, returns design briefs.
- **→ Dev.** Briefs, tokens, component references.
- **→ QA.** Visual regression target spec, a11y criteria.
- **→ Release Manager.** Visual changelog entries.

## Memory patterns

- **Per-project-per-Designer memory**:
  - `tokens` (palette, typography, spacing, motion).
  - `components` (inventory with usage count).
  - `decisions` (visual choices w/ rationale).
  - `references` (mood board pointers, respected competitor patterns).
  - `violations` (caught anti-template usages).

## Dashboard surfaces

- **Design system** page per project (tokens + components + examples).
- **Design briefs** per story.
- **Visual regression review** board with approve / request-change.
- **Mood board / references** library.

## New tools

| Tool | Purpose |
|---|---|
| `frontend-design` skill | Already present; invoke for ambitious UI work |
| Figma MCP (optional) | Pull frames into briefs |
| Lightweight image tools (Pillow / sharp) | Crop/annotate screenshots |
| Visual regression (Playwright snapshots) | Shared with QA |

## Success metrics

- Anti-template checklist pass rate = 100% on shipped UI stories.
- Component duplicates shipped = 0.
- Visual regression noise (unintended changes) trending down.
- A11y serious violations = 0 at ship.

## Rollout

1. **Foundation.** Codename, design-system.md, component inventory.
2. **Design brief per UI story.**
3. **Visual regression co-review with QA.**
4. **Motion & a11y guardrails.**
5. **Cross-project design principles** (promoted memory).
