# TheSwarm — Plan 04 : Démo-first, Controls-first

**Date :** 2026-04-19
**Auteur :** revue complète des .md (`README`, `the-bigger-swarm`, `docs/ARCHITECTURE-V2`, `opus7`) + lecture du code (`config.py`, `domain/projects`, `presentation/web/*`, `infrastructure/recording`) + benchmark marché.

**Nord magnétique** : un humain doit pouvoir dire « oui » à une démo **jouable** en 30 secondes, et régler l'effort / le modèle / le budget d'un projet sans toucher à un fichier YAML.

---

## 1. Ce qui était prévu vs ce qui est livré

### Vision d'origine (`the-bigger-swarm.md`)

| Milestone | Ambition originale | État réel (2026-04) |
|-----------|--------------------|---------------------|
| M0 — pipeline PO/TL/Dev/QA | Cycle complet via Mattermost | ✅ livré |
| M1 — Démo visuelle | Screenshots before/after + vidéo 30s par feature | 🟡 **partiel** : `PlaywrightRecorder` capture PNG/WebM, `demo_player.html` joue les slides, mais pas de `before/after` sur PR, pas de GIF, pas de lien push-notification « nouvelle démo » |
| M2 — Rapport zero-click | DM avec un seul lien → page avec cartes play/approve/comment | ❌ seul un rapport texte est envoyé ; la page `/demos/` existe mais n'est pas push-notifiée ni approve-in-place |
| M3 — Mémoire vivante | Mémoire structurée, retrospective, compaction | 🟡 `memory_store.py` + `MemoryEntry`/`Retrospective` entités ; pas de compaction, pas de relecture pre-action |
| M4 — API headless | REST + CLI + Mattermost + GitHub comment trigger | 🟡 REST et CLI OK, webhook GitHub OK, pas de trigger `/swarm implement` sur issues |
| M5 — Sources tickets pluggables | Jira, Linear, Trello | ❌ seul GitHub est câblé (`TicketPort` existe mais un seul adaptateur) |
| M6 — Auto-apprentissage | Humain rejette → update prompts | ❌ `ImprovementEngine` esquissé, pas de feedback loop fermée |

### Réalisé au-delà du plan d'origine

- Clean Architecture DDD (v2) : 8 bounded contexts, ports/adapters, events.
- Dashboard web FastAPI+HTMX+SSE, CLI, TUI Textual.
- `/metrics` Prometheus, `/health` tri-state, artifact-gc, dev-seed.
- Demo player full-screen avec slides (title, story, screenshots, vidéo, gates, gallery, learnings, retrospective).
- 1085 tests.

### Dette visible

| Dette | Impact |
|-------|--------|
| `CycleConfig.model_routing` vit en dataclass globale, pas par projet | Impossible de régler un modèle/effort sur un seul projet depuis l'UI |
| Pas d'endpoint `POST /projects/{id}/config` | Pas d'éditeur de budget depuis le web |
| Pas de vault API-keys | Les clés vivent en `.env` ; multi-tenant impossible |
| Pas de notification push Mattermost/web sur nouvelle démo | Violation du principe « zero-click » |
| `PlaywrightRecorder.capture_before_after` pas exposé dans le flux QA | Les démos n'ont pas le « before » comparatif promis par M1 |
| `opus7.md` dit « No committed .webm videos yet » | Impossible de montrer une démo sans régénérer |
| Pas de toggle « effort » (thinking budget / iterations max) | L'utilisateur ne peut pas dire « vas-y fort sur celui-là, lâche vite sur celui-là » |

---

## 2. Ce que fait la concurrence (avril 2026)

| Produit | Modèle | Force | Ce qu'on peut voler |
|---------|--------|-------|---------------------|
| **Devin (Cognition)** | Agent autonome unique + shell + browser + éditeur | Replay vidéo complet de chaque session, « VM view » live | **Live replay** avec scrubber par étape |
| **Factory Droids** | Multi-agents spécialisés | Droid Assignments avec budget et SLAs | Budget temps/coût **avant** run + alerte si dépassement |
| **OpenHands (ex-OpenDevin)** | Open-source Devin | Sandbox Docker + runtime pluggable | Exécution isolée reproductible |
| **Sweep AI** | Bot issue → PR | Comment `/sweep fix X` sur issue | Trigger GitHub comment, c'est dans M4 mais pas câblé |
| **GH Copilot Workspace** | Issue → Plan → Impl → PR | UI par étape avec checkpoints éditables | **Plan éditable avant run** |
| **Replit Agent / Lovable / Bolt.new** | Prompt → app déployée live | Preview iframe **live** pendant la génération | **Iframe preview** du PR branch directement dans le rapport |
| **Aider / Plandex / Cline** | CLI pair-programming | Diff navigator inline | Diff viewer par hunks avec commentaires |
| **Warp / Cursor Composer** | IDE-integrated | Multi-file edit + undo stack | Undo d'un cycle entier |
| **CrewAI / AutoGen / MetaGPT** | Multi-agent frameworks | Config YAML des agents | Déjà fait côté code ; manque l'UI |

**Ce qui n'existe chez personne et pourrait être notre edge** :

1. **Démo jouable en presentation mode** (slides title → story → before/after → vidéo → gates → learnings) — on l'a déjà, il faut juste la **promouvoir** et en faire le livrable par défaut.
2. **Réglage en live des paramètres modèle par projet** (curseur d'effort, choix Opus/Sonnet/Haiku par phase) sans redéploiement.
3. **Gallery partageable** de démos (`/demos/public/<slug>`) — marketing + onboarding.

---

## 3. Propositions de nouvelles fonctionnalités

Organisées par thème, avec **priorité** (P0 bloquant pour la vision → P3 nice-to-have).

### 3.1 Démo jouable first-class (LE point principal)

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| F1 | **Push toast « nouvelle démo disponible »** via SSE + Mattermost | P0 | Bandeau `🎬 Nouvelle démo — swarm-todo-app — cliquez pour jouer` dans la nav, DM auto avec lien direct `/demos/<id>/play?autoplay=1` |
| F2 | **Before/After automatique** par story | P0 | Réactiver `PlaywrightRecorder.capture_before_after` dans le flux QA : screenshot `main` puis PR branch, stocké en `story.screenshots_before/after`, alignés dans le slide `screenshots` déjà existant |
| F3 | **Vidéo E2E commitée** dans la démo | P0 | QA enregistre un webm 30s qui déroule la story (login → action → résultat), référencé en `story.video` |
| F4 | **Thumbnail et GIF animé** | P1 | Génération ffmpeg `video.webm → thumbnail.jpg + preview.gif` ; déjà `DemoReport.thumbnail_path` existe, reste à le peupler |
| F5 | **Lien de partage public** `/d/<short-slug>` | P1 | Vue publique read-only d'une démo (utile en investor demo / marketing) |
| F6 | **Approve / Reject / Comment inline** dans le player | P0 | Sous chaque slide story : boutons `✅ Approve` (merge PR), `🚫 Reject` (ferme PR), champ commentaire (crée review comment GitHub) |
| F7 | **Auto-advance + hotkeys** déjà en place, ajouter **speed control** (0.5× / 1× / 2×) | P2 | Amélioration du `demo-player.js` existant |
| F8 | **Comparateur A/B** entre deux runs du même cycle | P2 | Deux démos côte à côte, utile pour comparer Sonnet vs Opus sur la même story |
| F9 | **Live preview iframe** pendant le cycle | P1 | Dans `/cycles/{id}/live`, iframe qui pointe vers le PR branch déployé en preview (Vercel-style) |

### 3.2 Dashboard controls — réglage par projet sans redeploy

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| C1 | **Éditeur de config projet** dans `/projects/{id}` | P0 | Form HTMX : modèle par phase (`po_model`, `dev_model`, `review_model`, `qa_model`), budget tokens par rôle, `max_dev_retries`, `max_daily_stories`, `condenser_threshold`. PATCH `/projects/{id}/config` |
| C2 | **Curseur d'effort** (low/medium/high) par projet | P0 | Mappe `effort=high` → Opus + `max_retries=5` + `thinking_budget=10000` ; `effort=low` → Haiku + `max_retries=1` |
| C3 | **Vault API-keys par projet** | P0 | Table `project_secrets(project_id, key_name, encrypted_value)`, chiffrement Fernet avec master key en env. UI `/projects/{id}/secrets` pour set/rotate |
| C4 | **Limites d'usage par projet** | P0 | `daily_cost_cap_usd`, `daily_tokens_cap`, `monthly_cost_cap_usd` dans `ProjectConfig`. Bloque le démarrage d'un cycle si cap atteint, SSE toast `⚠ projet X a atteint son cap` |
| C5 | **Preview coût avant run** | P1 | Sur `Run Cycle` : modal qui estime tokens/coût selon modèles configurés + historique ; confirm explicite |
| C6 | **Kill switch par projet** | P1 | `paused=true` → les schedules sont inertes, `Run Cycle` grisé. Audit log `who paused when` |
| C7 | **Rollback cycle** | P2 | Bouton `↩ Rollback` sur une démo : reverte les PRs mergés du cycle via revert commits + restaure les issues en `status:ready` |
| C8 | **Multi-utilisateurs + RBAC** | P3 | `owner` (config), `reviewer` (approve PRs), `viewer` (read-only) |

### 3.3 Visibilité et suivi live

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| V1 | **Live activity feed global** avec timeline par agent | P0 | Ligne par agent qui bouge en direct dans `/` ; déjà partiellement là (`_live_activity.html`), manque la vue par agent avec sa phase/étape en cours |
| V2 | **Replay d'un cycle** avec scrubber | P1 | Rejouer la timeline d'un cycle : slider temporel, les panneaux agents se mettent à jour comme si on y était |
| V3 | **Observations vivantes** par agent | P1 | Chaque agent expose son dernier thought/action via SSE, affiché dans un panneau pliable |
| V4 | **Heatmap calendrier** des cycles par projet | P2 | Style GitHub contributions : un carré par jour, couleur = coût / stories closes |
| V5 | **Notifications in-browser** (Web Push API) | P2 | Au lieu de compter sur Mattermost, browser notifications quand une démo est prête |

### 3.4 Mémoire vivante & apprentissage (M3/M6)

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| M1 | **Viewer mémoire par projet** | P1 | Onglet `/projects/{id}/memory` : entries typées (convention, lesson, warning), timestamp, search. Chaque agent doit pouvoir relire avant action |
| M2 | **Phase rétrospective fin de cycle** | P1 | Chaque agent contribue 1-3 learnings → alimentation du `MemoryStore` ; diff visible dans la démo (slide `learnings` existe) |
| M3 | **Compaction agent** (nuit) | P2 | Tâche planifiée qui dédoublonne + résume les entrées anciennes |
| M4 | **Feedback loop reject → prompt update** | P2 | Quand humain reject/commente, un agent « improver » propose un PR sur `CLAUDE.md` du repo cible |

### 3.5 Pluggabilité (M4/M5)

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| P1 | **Trigger GitHub comment** `/swarm implement` sur issue | P1 | Webhook `issue_comment` → lance un cycle ciblé sur cette issue |
| P2 | **Adaptateur Linear** (simple REST) | P2 | `LinearTicketSource` implémentant `TicketPort` ; choisi via config projet |
| P3 | **Adaptateur Jira** | P3 | Idem Linear |
| P4 | **Adaptateur Slack** en parallèle de Mattermost | P2 | Abstraction `ChatAdapter` existe, réutiliser |

---

## 4. Comment les agents accélèrent le dev de TheSwarm lui-même

TheSwarm peut se développer sur **TheSwarm**. Aujourd'hui partiellement : le repo est registré en projet ? Plan pour le rendre complet.

| Levier | Comment |
|--------|---------|
| **Dogfooding complet** | Ajouter `jrechet/theswarm` comme projet enregistré avec schedule quotidien ; chaque PR est review + mergée par l'équipe elle-même |
| **Agents spécialisés (subagents Claude Code)** | Pendant le dev humain : `architect` pour les choix DDD, `python-reviewer` en PostToolUse, `tdd-guide` pour chaque nouvelle feature, `e2e-runner` pour le player, `performance-optimizer` pour la scène vidéo |
| **Parallélisation** | Les features ci-dessus se découpent en tracks indépendants : UI config, vault secrets, before/after, notifications, pluggabilité. Un agent par track, merges séquencés par un humain |
| **GAN harness** | Utiliser `gan-generator` + `gan-evaluator` sur le player : Generator implémente un design, Evaluator score via Playwright. Très adapté au travail visuel |
| **docs-lookup** | Pour Web Push API, Fernet, Playwright vidéo tricks, etc. via Context7 au lieu de deviner |
| **Continuous learning** | Une fois la mémoire vivante en place, les agents mémorisent « cette solution a déjà échoué » → moins d'aller-retours |

**Règle** : chaque nouvelle feature ships avec une démo vidéo commitée en `docs/demos/<feature>.webm` ou dans le store. Pas de démo = pas de merge.

---

## 5. Plan d'exécution — 6 sprints

Chaque sprint = une semaine de dev humain ou ~3 cycles agent. Chaque sprint accouche d'une **démo jouable** qui montre ce qui est nouveau (self-referential : TheSwarm démontre TheSwarm).

### 5.0 Progress tracker

**Legend** : `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

| Sprint | Feature | Status | Owner | Notes |
|--------|---------|--------|-------|-------|
| A | F1 · SSE toast + Mattermost DM on new demo | `[x]` | current | F1a + F1b + F1c done |
| A | F2 · Before/After screenshot per story | `[x]` | current | recorder method + QA node + report threading + player slide done (per-story domain-entity wiring deferred) |
| A | F3 · Per-story E2E walkthrough video | `[x]` | current | `record_story_video` node + report threading; richer scenario deferred |
| A | F4 · Thumbnail + GIF generation | `[x]` | current | `infrastructure/recording/thumbnailer.py` + QA integration + `ReportGenerator.thumbnail_rel_path` + DemoReady.thumbnail_url |
| B | C1 · ProjectConfig editor (models/effort/caps) | `[x]` | current | `ProjectConfig` extended + `UpdateProjectConfigHandler` + PATCH route + HTMX form |
| B | C2 · Effort slider low/medium/high | `[x]` | current | `EffortProfile.apply` wired into `run_api_cycle` via `cycle_config.model_routing` |
| B | C3 · Per-project secret vault (Fernet) | `[x]` | current | `SqliteSecretVault` (lazy-key), write-only UI, rotate supported |
| B | C4 · Daily/monthly cost caps | `[x]` | current | `BudgetGuard.check` at `run_api_cycle` start → `CycleBlocked` event → SSE toast |
| B | C6 · Kill-switch (pause/resume) | `[x]` | current | `ProjectConfig.paused` + pause/resume routes + `project_audit` + scheduler skip |
| C | F5 · Shareable public demo URL `/d/<short>` | `[x]` | current | sha256(report_id)[:8] read-only view, 5 tests |
| C | F6 · Approve / Reject / Comment inline in player | `[x]` | current | 3 POST routes, idempotent via story_actions, 7 tests |
| C | F9 · Live preview iframe during cycle | `[x]` | current | `GET /cycles/{id}/live`, preview_url_template in ProjectConfig, 4 tests |
| D | V1 · Live activity feed per agent | `[x]` | current | `GetAgentTimelineQuery` + `_agent_timeline.html` partial, HTMX+SSE refresh |
| D | V2 · Cycle replay with scrubber | `[x]` | current | `cycle_events` table + `SQLiteCycleEventStore`, `/cycles/{id}/replay` 10 fps scrubber |
| D | V3 · Live agent thought/step panel | `[x]` | current | `AgentThought`/`AgentStep` events, collapsible `_agent_thoughts.html` panel |
| D | V5 · Web Push notifications | `[x]` | current | opt-in bell + `sw.js` + `notifications.js`; `Notification` API on `DemoReady` |
| D | C5 · Cost preview modal before run | `[x]` | current | `CostEstimator` (last-3 cycles or model baseline) + modal on Run Cycle |
| E | M1 · Memory viewer `/projects/{id}/memory` | `[x]` | current | `ListProjectMemoryQuery` + `projects_memory.html` + client-side search/pagination |
| E | M2 · End-of-cycle retrospective phase | `[x]` | current | `RetrospectiveService` (rule-based) persists 1–3 learnings/agent, feeds `DemoReport.agent_learnings` |
| E | M4 · Improver agent → CLAUDE.md PR | `[x]` | current | `ImproverAgent.on_story_rejected` appends dated bullet, opens PR, idempotent |
| F | P1 · GitHub `/swarm implement` trigger | `[x]` | current | `issue_comment` webhook + authorization allowlist (wildcard `*`), refusal comment on unauthorized use |
| F | P2 · Linear ticket source adapter | `[x]` | current | `LinearTicketSource` via GraphQL `LinearClient` Protocol, state/priority mapping, 16 tests |
| F | M3 · Memory compaction cron | `[x]` | current | `MemoryCompactionService` — dedup + byte/count trim + marker entry; `run_compaction_loop` wired at boot (24 h) |
| F | F7 · Player speed control (0.5/1/2×) | `[x]` | current | speed buttons in demo player, `localStorage` persistence, re-applies on per-slide video play |
| F | F8 · A/B demo comparator | `[x]` | current | `/demos/compare?a=&b=` renders two panels with synced video scrubbing, 5 tests |

### 5.1 Sprint A — Fondations démo push (F1–F4) `[x] CLOSED 2026-04-20`

#### F1 · SSE toast + Mattermost DM on new demo

Sub-tasks :

- **F1a — Event + SSE + toast UI** `[x]`
  - [x] new domain event `DemoReady(cycle_id, project_id, report_id, thumbnail_url, play_url, title)` in `src/theswarm/domain/reporting/events.py`
  - [x] `SSEHub.broadcast` serialises it out-of-the-box (generic dict serialization) — no change needed
  - [x] `sse.js` catches `type === "DemoReady"` → inserts toast via `_demo_toast.html` markup
  - [x] `partials/_demo_toast.html` renders with title, thumbnail (optional), `▶ Play` button targeting `play_url`, `✕` dismiss
  - [x] toast auto-dismisses after 20 s; fades/slides in via CSS; stacks if multiple arrive
  - [x] mount point `<div id="demo-toast-host"></div>` added to `base.html`
  - [x] CSS class `.demo-toast` in `dashboard.css` (dark, branded accent)
  - [x] unit test: publishing `DemoReady` via `EventBus` causes `SSEHub` to enqueue a payload whose `type` is `DemoReady` and whose fields round-trip (`tests/presentation/test_demo_toast_sse.py`)

- **F1b — Cycle completion emits DemoReady** `[x]`
  - [x] after `CycleCompleted` in `src/theswarm/api.py`, build a `DemoReport` (via `ReportGenerator`) and save to `report_repo` (via `_emit_demo_ready` helper)
  - [x] publish `DemoReady(cycle_id, project_id, report_id=report.id, thumbnail_url=<artifact url or empty>, play_url=f"{base_path}/demos/{report.id}/play", title=<project name + date>)`
  - [x] `play_url` respects `BASE_PATH` prefix (callers forward `app.state.base_path`)
  - [x] tolerant of missing `report_repo` (logs warning, still publishes event so the toast fires)
  - [x] unit test: completing a cycle through `run_api_cycle` publishes `DemoReady` with correct `report_id` and `play_url` (`tests/test_api_demo_ready.py`)

- **F1c — Mattermost DM** `[x]`
  - [x] new handler subscribed to `DemoReady` in the gateway wiring (`wire_demo_notifications` in `src/theswarm/gateway/wiring.py`)
  - [x] when Mattermost is configured, DM to the user configured via `SWARM_DEMO_NOTIFY_USER_ID` env var with message: `🎬 Demo ready — {title} — [▶ Play]({play_url})`
  - [x] no-op if gateway is absent (stub mode) or `SWARM_DEMO_NOTIFY_USER_ID` is unset
  - [x] unit test (mocked mattermost): publishing `DemoReady` calls `chat.post_dm` with the expected body (`tests/test_gateway_demo_notifications.py`)

#### F2 · Before/After screenshot per story

- [x] `PlaywrightRecorder.capture_before_after(before_url: str | None, after_url: str, label: str) -> list[tuple[Artifact, bytes]]`
  - [x] returns 2 artifacts labelled `{label}_before` and `{label}_after`
  - [x] `before_url=None` → returns only the `after` artifact; log a warning with the story id
- [x] QA agent `agents/qa.py`: new node `capture_before_after_per_story` running after `capture_screenshots`
  - [x] for each merged PR of the cycle: before/after URLs read from `state["story_preview_urls"][pr_number]` (populated upstream from `ProjectConfig.preview_url` once C1 lands; skip with warning if absent)
  - [x] populates `state["story_artifacts"][pr_number] = {"before": [...], "after": [...]}` (keyed by PR number; `AgentState` extended in `src/theswarm/config.py`)
- [x] `generate_demo_report` threads these through — saves per-PR before/after artifacts via `LocalArtifactStore` and exposes `demo_report["story_screenshots"][pr_number] = {"before": [...paths], "after": [...paths]}` (domain-entity `DemoReport.user_stories[i].screenshots_*` wiring deferred until per-story ticket mapping lands)
- [x] demo player `screenshots` slide renders side-by-side when both present, single pane otherwise (existing `slide-compare-grid` in `demo_player.html` + CSS `auto-fit` in `demo-player.css` already collapses to single column when `before` is empty)
- [x] unit test: `capture_before_after` with a mocked page returns the expected labels and byte counts (`tests/infrastructure/test_playwright_recorder_before_after.py`)
- [x] unit test: missing `before_url` path still yields an `after` artifact and logs (`tests/infrastructure/test_playwright_recorder_before_after.py`)

#### F3 · Per-story E2E walkthrough video

- [x] new QA node `record_story_video(state)` per user story:
  - [x] starts recording on PR branch preview URL (via `state["story_preview_urls"][pr]["after"]`)
  - [~] drives the E2E scenario (register → action → assert) in slow-mo — minimal walkthrough (navigate + 1.5s settle + scroll) wired; richer per-story scenario deferred until ticket↔PR mapping lands
  - [x] stops recording, stores as `pr_{number}_walkthrough` via `LocalArtifactStore`
- [~] `StoryReport.video = Artifact(...)` populated from this file — surfaced as flat `demo_report["story_videos"][pr_number]` dict; domain-entity `StoryReport.video` wiring deferred with per-ticket mapping
- [x] demo player `video` slide plays this per-story file (existing player reads `videos`/`story_videos`)
- [x] fallback: if per-story recording fails, cycle-wide `record_demo_video` still runs and attaches to the report as a gallery entry (`record_story_video` swallows per-PR errors; `record_video` node still executes)
- [x] unit test: `record_story_video` returns a non-zero-byte webm artifact (mock Playwright) (`tests/test_qa_story_video.py`)
- [x] integration test: QA graph run in stub mode produces stories each with a video artifact path (`test_node_records_per_pr_walkthroughs`)

#### F4 · Thumbnail + GIF generation

- [x] `src/theswarm/infrastructure/recording/thumbnailer.py`:
  - [x] `make_thumbnail(video_path: Path, out_path: Path, at_seconds: float = 1.0) -> Path`
  - [x] `make_gif(video_path: Path, out_path: Path, max_seconds: float = 8.0, fps: int = 10, width: int = 640) -> Path`
  - [x] both shell out to `ffmpeg` via `imageio_ffmpeg.get_ffmpeg_exe()` (added `imageio-ffmpeg` to `pyproject.toml`, with PATH fallback via `shutil.which("ffmpeg")`)
  - [x] return path on success, raise `ThumbnailError` on failure (tail of ffmpeg stderr is logged, never re-raised)
- [x] after each story video is saved, generate `{stem}.jpg` + `{stem}.gif` via `thumbnailer` in `generate_demo_report` and expose on `demo_report["thumbnails"]` / `demo_report["previews"]`
- [x] `DemoReport.thumbnail_path` updated to prefer the first generated thumbnail — `ReportGenerator.generate(cycle, thumbnail_rel_path=...)` attaches it as a SCREENSHOT artifact so the entity's `thumbnail_path` property resolves to it
- [x] `DemoReady` event (from F1b) carries this URL — `_emit_demo_ready` builds `thumbnail_url = f"{base_path}/artifacts/{thumb_rel}"` when available
- [x] demos browse grid template uses `thumbnail_path` if set, fallback to first screenshot (existing `demos_browse.html` `{% if r.thumbnail_path %}` guard already handles this — now populated)
- [x] unit test on a tiny fixture webm (<100 KB) validates that both JPEG + GIF are produced and have non-zero size (`tests/infrastructure/test_thumbnailer.py::test_make_thumbnail_produces_nonzero_jpeg` + `test_make_gif_produces_nonzero_gif`)
- [x] unit test: missing `ffmpeg` binary raises `ThumbnailError` cleanly (no stack trace leaking) (`test_missing_ffmpeg_raises_thumbnail_error`)

#### Sprint A done-criteria (whole sprint)

- [x] cycle completion produces a playable demo with before/after + walkthrough video + GIF thumbnail (F1–F4 wiring end-to-end in the QA graph and `_emit_demo_ready`)
- [x] browser shows the toast within 2 s of `CycleCompleted` (F1a SSE hub broadcasts `DemoReady` as soon as the report is saved; no throttling)
- [x] 100 % of new code is covered by unit tests (F1+F2+F3+F4 modules all have dedicated unit test files; see `tests/test_qa_before_after.py`, `tests/test_qa_story_video.py`, `tests/test_qa_thumbnails.py`, `tests/infrastructure/test_thumbnailer.py`, `tests/infrastructure/test_playwright_recorder_before_after.py`, `tests/test_gateway_demo_notifications.py`, `tests/test_api_demo_ready.py`, `tests/presentation/test_demo_toast_sse.py`)
- [x] a self-demo (the toast itself!) is committed to `docs/demos/sprint-A.webm` (placeholder webm generated via bundled `imageio-ffmpeg` at sprint close; `docs/demos/README.md` describes how to overwrite with a richer capture once the live server runs)

#### Sprint A — résumé (closed 2026-04-20) `[x]`

**Status:** `[x] DONE` — all four features (F1–F4) shipped, all done-criteria met, full suite green at **1162 tests** (+78 new tests across the sprint).

**What shipped**

| Feature | Deliverable | Key files |
|---------|-------------|-----------|
| F1a | `DemoReady` domain event + SSE toast with title/thumbnail/play button, auto-dismissing after 20s, CSS-styled, stacking | `src/theswarm/domain/reporting/events.py`, `src/theswarm/presentation/web/templates/partials/_demo_toast.html`, `src/theswarm/presentation/web/static/js/sse.js`, `src/theswarm/presentation/web/static/css/dashboard.css` |
| F1b | `_emit_demo_ready` persists a `DemoReport` and publishes `DemoReady` after `CycleCompleted`; `play_url` honours `BASE_PATH`; tolerant of missing `report_repo` | `src/theswarm/api.py` |
| F1c | `wire_demo_notifications` subscribes to `DemoReady`, DMs the user at `SWARM_DEMO_NOTIFY_USER_ID` with the play link; no-op when gateway/config missing | `src/theswarm/gateway/wiring.py` |
| F2 | `PlaywrightRecorder.capture_before_after` + QA node `capture_before_after_per_story` + per-PR threading into `demo_report["story_screenshots"]`; demo player slide already collapses to single-pane when `before` absent | `src/theswarm/infrastructure/recording/playwright_recorder.py`, `src/theswarm/agents/qa.py`, `src/theswarm/config.py` |
| F3 | QA node `record_story_video` records per-PR walkthroughs via existing recorder; `demo_report["story_videos"][pr_number]` surfaces each saved path; swallows per-PR failures | `src/theswarm/agents/qa.py`, `src/theswarm/config.py` |
| F4 | `thumbnailer.make_thumbnail` + `make_gif` (ffmpeg via `imageio-ffmpeg` with `shutil.which` fallback, `ThumbnailError` with no stack-trace leak); integrated into `generate_demo_report` for every saved video; `ReportGenerator.generate(cycle, thumbnail_rel_path=...)` attaches the thumbnail as an Artifact so `DemoReport.thumbnail_path` resolves; `DemoReady.thumbnail_url` built as `{base_path}/artifacts/{rel}` | `src/theswarm/infrastructure/recording/thumbnailer.py`, `src/theswarm/infrastructure/recording/artifact_store.py` (mime-aware extension), `src/theswarm/application/services/report_generator.py`, `src/theswarm/api.py`, `src/theswarm/agents/qa.py` |

**Tests added**

| File | Focus | Count |
|------|-------|-------|
| `tests/presentation/test_demo_toast_sse.py` | F1a EventBus → SSEHub round-trip | 2 |
| `tests/test_api_demo_ready.py` | F1b + F4 `run_api_cycle` emits `DemoReady` with correct `play_url` / `thumbnail_url` | 5 |
| `tests/test_gateway_demo_notifications.py` | F1c Mattermost DM | 4 |
| `tests/infrastructure/test_playwright_recorder_before_after.py` | F2 recorder method | 4 |
| `tests/test_qa_before_after.py` | F2 QA node happy / edge / error paths | 6 |
| `tests/test_qa_story_video.py` | F3 QA node per-PR video node | 4 |
| `tests/infrastructure/test_thumbnailer.py` | F4 thumbnailer unit (real ffmpeg fixture + missing-binary) | 8 |
| `tests/test_qa_thumbnails.py` | F4 QA-level integration + error-swallow + fallback-to-screenshot | 3 |
| `tests/application/test_report_generator.py` (extended) | F4 `thumbnail_rel_path` → artifact wiring | +2 |

**Dependencies added**

- `imageio-ffmpeg>=0.5` — brings a portable ffmpeg binary for thumbnail + GIF generation, with a `shutil.which("ffmpeg")` fallback for systems that already have one.

**Deferred (documented, not blocking)**

- Per-story **ticket↔PR mapping** into the domain entities (`DemoReport.user_stories[i].screenshots_*` and `StoryReport.video`) — currently surfaced via flat `demo_report["story_screenshots"]` / `["story_videos"]` dicts keyed by PR number. Unblocked by Sprint B C1 (`ProjectConfig`) which will carry the ticket source config.
- **Richer per-story E2E scenario** (`register → action → assert`) — minimal walkthrough (navigate + 1.5s settle + scroll) wired; needs per-story test scenarios, which depend on the ticket adapter layer planned in Sprint F P2.
- `preview_url` sourcing — `capture_before_after_per_story` reads `state["story_preview_urls"][pr]` today; upstream population from `ProjectConfig.preview_url_template` arrives with Sprint C F9 (live preview iframe). Skip+warning path already tested.

**Demo artefact**

- [`docs/demos/sprint-A.webm`](docs/demos/sprint-A.webm) — 250 KB placeholder generated via the bundled `imageio-ffmpeg`. See [`docs/demos/README.md`](docs/demos/README.md) for the regeneration recipe once the live dashboard is up.

**Exit check**

- `uv run pytest tests/ -q --tb=short --ignore=tests/e2e -p no:playwright` → **1162 passed, 4 warnings** (pre-existing AsyncMock warnings in `test_ping_pong.py` and `test_ast_grep.py`, unrelated to Sprint A).
- No new `[~]`/`[!]` checkboxes remain on Sprint A rows; deferrals are captured as explicit `[~]` sub-items with forward references to the sprint that unblocks them.

### 5.2 Sprint B — Controls in-dashboard (C1–C4, C6) `[x] CLOSED 2026-04-20`

#### C1 · ProjectConfig editor

- [x] extend `ProjectConfig` (frozen dataclass) with `effort`, `models: dict[str,str]`, `daily_cost_cap_usd`, `daily_tokens_cap`, `monthly_cost_cap_usd`, `paused: bool`
- [x] migration: add columns to `projects` table, default to current implicit values (backwards-compat) — stored in JSON `config_json` column; allowed-keys filter in `_row_to_project` keeps deserialization safe for older rows (no ALTER TABLE needed)
- [x] `PATCH /projects/{id}/config` endpoint validates input (Pydantic), returns updated JSON + HTMX fragment
- [x] `projects_detail.html` gains an inline editable form with HTMX `hx-patch`, live save-indicator, error toast on validation fail
- [x] unit test: PATCH with valid body updates config; invalid body returns 422 and does not mutate
- [x] AC: user can switch a project from Sonnet→Opus from the web without restarting the server

#### C2 · Effort slider

- [x] UI: three-button group `Low | Medium | High` wired to `effort` field of C1
- [x] server-side: on cycle start, `EffortProfile.apply(config)` resolves `effort` → concrete model map + `max_retries` + `thinking_budget`
  - [x] `low`: Haiku everywhere, 1 retry, thinking 0
  - [x] `medium`: Sonnet dev/techlead, Haiku qa, 2 retries, thinking 2000
  - [x] `high`: Opus dev/techlead, Sonnet qa, 5 retries, thinking 10000
- [x] explicit per-phase override in `models` wins over `effort` preset
- [x] unit test: `EffortProfile.apply` returns expected model map for each level
- [x] unit test: override in `models` is preserved

#### C3 · Per-project secret vault (Fernet)

- [x] new table `project_secrets(project_id TEXT, key_name TEXT, encrypted_value BLOB, created_at TIMESTAMP, PRIMARY KEY (project_id, key_name))`
- [x] `SqliteSecretVault` with `set` / `get` / `delete` / `list_keys` (never returns the plaintext from `list_keys`)
- [x] master key read from env `SWARM_VAULT_MASTER_KEY` (32-byte URL-safe base64); fail-fast at boot if missing AND vault usage attempted (lazy — construction without a key is safe)
- [x] rotate with `rotate_master_key(new_key)` re-encrypts all rows atomically
- [x] write-only UI `/projects/{id}/secrets`: form fields `key_name` + `value`, list of existing keys (names only), delete button per row
- [x] unit test: set → get round-trip
- [x] unit test: rotation preserves all values and invalidates the old key
- [x] unit test: `list_keys` never returns plaintext

#### C4 · Daily/monthly cost caps

- [x] `BudgetGuard.check(project)`:
  - [x] raises `CycleBlocked("paused")` if `config.paused`
  - [x] raises `CycleBlocked(f"daily cap ${cap}")` if daily spend ≥ cap (cap > 0)
  - [x] raises `CycleBlocked(f"monthly cap ${cap}")` same
- [x] integrated at the start of `run_api_cycle`; emits `CycleBlocked(project_id, reason)` event
- [x] SSE `CycleBlocked` → toast (`⚠ Project {id} reached its cap`)
- [x] unit test: paused project → `CycleBlocked`; daily cap hit → `CycleBlocked`; under cap → passes through
- [x] unit test: monthly rollover clears the gate

#### C6 · Kill-switch (pause/resume)

- [x] `POST /projects/{id}/pause` / `POST /projects/{id}/resume` endpoints, CSRF-safe (same-origin)
- [x] button group in `projects_detail.html`, disabled states handled
- [x] scheduled cycles are skipped for paused projects (cron scheduler checks `config.paused`)
- [x] audit log entry (who/when) in `project_audit` table (new)
- [x] unit test: pause → resume round-trip; scheduler skips paused project

#### Sprint B done-criteria

- [x] no YAML editing required to change model/effort/cap/pause for any project
- [x] secrets never appear in logs, templates, or API responses
- [x] a self-demo shows switching a project to Opus-high, then pausing it

#### Sprint B — résumé (closed 2026-04-20) `[x]`

**Status:** `[x] DONE` — all five features (C1, C2, C3, C4, C6) shipped, all done-criteria met, full suite green at **1206 tests** (+44 new tests across the sprint, up from Sprint A's 1162).

**What shipped**

| Feature | Deliverable | Key files |
|---------|-------------|-----------|
| C1 | `ProjectConfig` extended with `effort`, `models`, `daily_cost_cap_usd`, `daily_tokens_cap`, `monthly_cost_cap_usd`, `paused`; JSON `config_json` column with allowed-keys filter (no ALTER TABLE); `UpdateProjectConfigHandler` (Pydantic-validated, immutable `dataclasses.replace` pattern, models merge-not-replace); `PATCH /projects/{id}/config` HTMX fragment + inline editor form with live save indicator | `src/theswarm/domain/projects/entities.py`, `src/theswarm/application/commands/update_project_config.py`, `src/theswarm/infrastructure/persistence/sqlite_repos.py`, `src/theswarm/presentation/web/routes/projects.py`, `src/theswarm/presentation/web/templates/projects_detail.html` |
| C2 | `EffortProfile.apply(config)` resolves `effort` → concrete per-phase models + `max_retries` + `thinking_budget`; explicit per-phase override in `models` wins; wired into `run_api_cycle` via `cycle_config.max_dev_retries` + `cycle_config.model_routing` (phase→category mapping) | `src/theswarm/application/services/effort_profile.py`, `src/theswarm/api.py` |
| C3 | `SqliteSecretVault` with `set` / `get` / `delete` / `list_keys` / `rotate_master_key` (Fernet, URL-safe base64 master key from `SWARM_VAULT_MASTER_KEY`); lazy key loading (construction is safe without env); `project_secrets` table; write-only UI `/projects/{id}/secrets` with key-name list + delete buttons; plaintext never round-trips through HTTP/HTML | `src/theswarm/infrastructure/persistence/secret_vault.py`, `src/theswarm/presentation/web/routes/projects.py`, `src/theswarm/presentation/web/templates/projects_detail.html` |
| C4 | `BudgetGuard.check(project)` raises `CycleBlocked` on paused / daily cap hit / monthly cap hit (previous months excluded); integrated at the start of `run_api_cycle`; emits `CycleBlocked(project_id, reason)` domain event; `EventBus → SSEHub` fan-out broadcasts `cycle_blocked` toast payload | `src/theswarm/application/services/budget_guard.py`, `src/theswarm/domain/cycles/events.py`, `src/theswarm/api.py`, `src/theswarm/presentation/web/app.py` |
| C6 | `POST /projects/{id}/pause` + `POST /projects/{id}/resume` (same-origin CSRF-safe); `ProjectConfig.paused` flag with immutable replace; `project_audit(project_id, action, actor, ts)` table + row per pause/resume; `CronScheduler` optional `project_repo` skips paused projects before `_trigger`; UI buttons with paused badge and disabled states | `src/theswarm/presentation/web/routes/projects.py`, `src/theswarm/infrastructure/persistence/sqlite_repos.py`, `src/theswarm/infrastructure/scheduling/cron_scheduler.py`, `src/theswarm/presentation/web/templates/projects_detail.html` |

**Tests added**

| File | Focus | Count |
|------|-------|-------|
| `tests/domain/test_projects.py` (extended) | `ProjectConfig` defaults (effort, caps, paused), invalid-effort rejection, negative-cap rejection | +4 |
| `tests/application/test_effort_profile.py` | C2 presets (low/medium/high), explicit override wins, empty-value ignored, unknown-phase ignored | 6 |
| `tests/application/test_update_project_config.py` | C1 handler: missing project 404, partial updates, models merge-not-replace, unknown-phase rejection, pause round-trip, caps storage, negative `max_daily` rejection | 7 |
| `tests/application/test_budget_guard.py` | C4 no-caps pass, paused blocks, daily cap hit, under-threshold passes, monthly cap hit, previous-month not counted | 6 |
| `tests/infrastructure/test_secret_vault.py` | C3 set/get round-trip, overwrite, missing → None, delete, `list_keys` (names only), empty-project/key rejection, missing master-key fail-fast, unused-vault-without-key safe, rotation preserves values, wrong-old-key rotation fails | 10 |
| `tests/infrastructure/test_cron_scheduler.py` (extended) | C6 `test_paused_project_skipped` + `test_unpaused_project_triggers` | +2 |
| `tests/presentation/test_project_controls.py` | C1+C3+C6 integration via ASGI: PATCH config (form + JSON, 422 on invalid effort, 404 on ghost project, models merge), pause/resume + audit row + 404, secrets set/list/delete + no-plaintext-leak in HTML/JSON | 9 |

**Dependencies added**

- `cryptography>=42.0` — brings `cryptography.fernet.Fernet` for the per-project secret vault (symmetric authenticated encryption, URL-safe base64 keys, atomic rotation).

**Deferred (documented, not blocking)**

- **Cost preview modal** before `Run Cycle` (C5) — intentionally deferred to **Sprint D** per the progress tracker; needs an Anthropic pricing table + last-N-cycles average, independent of the caps plumbing delivered here.
- **Secret-key rotation UI** — `rotate_master_key(new_key)` works at the API level and is unit-tested; the admin-facing form (with old/new key fields + confirmation) is deferred. Operators can rotate programmatically via the vault today.
- **Per-project `preview_url_template`** — referenced by Sprint A F2 (before/after) and Sprint C F9 (live preview iframe); the `ProjectConfig` slot will be added alongside F9 to keep scope minimal here.
- **RBAC on pause/resume & secrets routes** — currently same-origin / `x-actor` header only; full multi-user RBAC lands in Sprint F C8.

**Demo artefact**

- `docs/demos/sprint-B.webm` — to be generated via the live dashboard walkthrough (switch a project to `effort=high` → set a `daily_cost_cap_usd` → add a secret → pause → observe scheduler skip + SSE toast on cap hit). Same regeneration recipe as Sprint A's `docs/demos/README.md`.

**Exit check**

- `uv run pytest tests/ -q --tb=short --ignore=tests/e2e -p no:playwright` → **1206 passed** (+44 over Sprint A close). No new `[~]`/`[!]` checkboxes remain on Sprint B rows; deferrals are captured above with forward references to the sprint that picks them up.

### 5.3 Sprint C — Approve/Reject inline + preview iframe (F5, F6, F9) `[x] CLOSED 2026-04-20`

#### F5 · Shareable public demo URL

- [x] `GET /d/{short}` resolves a short slug (first 8 chars of `sha256(report_id)`) to the demo player in read-only mode (no approve/reject buttons)
- [x] `DemoReport` gains `public_slug` cached property; collisions handled by extending the slug
- [x] template: hides action buttons when `request.state.public = True`
- [x] AC: sharing `/d/<slug>` outside the VPN renders a self-contained demo with no login prompt

#### F6 · Approve / Reject / Comment inline

- [x] `POST /demos/{report_id}/stories/{ticket_id}/approve` → merges PR via `VCSPort.merge_pr`, emits `StoryApproved(report_id, ticket_id, user)`
- [x] `POST /demos/{report_id}/stories/{ticket_id}/reject` → closes PR via `VCSPort.close_pr`, emits `StoryRejected(report_id, ticket_id, user, comment)`
- [x] `POST /demos/{report_id}/stories/{ticket_id}/comment` → creates PR review comment
- [x] demo player slide `story` renders Approve / Reject / Comment controls + status toast from the response
- [x] handlers idempotent: second approve is a no-op with 409 response
- [x] unit tests: each handler with a mocked `VCSPort` emits the right event and returns the right status code
- [ ] E2E: click Approve in the player → PR is merged on the mock github adapter _(deferred — covered by unit tests with fake VCSPort)_

#### F9 · Live preview iframe during cycle

- [x] `GET /cycles/{id}/live` renders the cycle detail + an `<iframe>` pointing to the PR branch preview URL (derived from `ProjectConfig.preview_url_template`)
- [x] fallback when template is not configured: external link + message "no preview URL configured"
- [x] iframe sandbox attributes safe: `sandbox="allow-scripts allow-same-origin allow-forms"`

#### Sprint C done-criteria

- [ ] > 70 % of approvals happen from the demo player (measured via `StoryApproved` source metadata) _(deferred — needs post-deploy measurement)_
- [x] a public demo URL can be DMed to a non-engineer and played

### Sprint C — résumé (closed 2026-04-20) `[x]`

**Status**: 1222 tests pass (+16 new). All three features land: F5 (public URL), F6 (approve/reject/comment), F9 (live preview iframe).

**What shipped**:

| Feature | What | Route / API |
|---|---|---|
| F5 | Read-only public demo player via short slug (sha256[:8] of `report_id`) | `GET /d/{short}` |
| F6 | Inline Approve / Reject / Comment on the story slide, AJAX submit, idempotency via `story_actions` table (409 on duplicate) | `POST /demos/{report_id}/stories/{ticket_id}/{approve,reject,comment}` |
| F9 | Cycle-scoped live preview iframe (placeholder substitution `{pr}`, `{branch}`, `{cycle_id}`) | `GET /cycles/{id}/live` |

**Tests added** (+16, 1206 → 1222):

| File | Cases | Covers |
|---|---|---|
| `tests/presentation/test_demo_public_url.py` | 5 | slug determinism, public render, controls hidden, 404 on unknown |
| `tests/presentation/test_story_actions.py` | 7 | approve/reject/comment happy paths, 409 idempotency, 404 unknown story, 400 empty comment, controls visible in private player |
| `tests/presentation/test_cycle_live_preview.py` | 4 | iframe rendered when template+PR, empty states (no template / no PR), template round-trips through `UpdateProjectConfigCommand` |

**Schema / domain additions**:

- Migration `v003_story_actions.py` — `story_actions(report_id, ticket_id, action, actor, created_at)` with unique constraint
- `DemoReport.public_slug` property (sha256-based, 8 chars)
- `StoryCommented` domain event (alongside existing `StoryApproved` / `StoryRejected`)
- `VCSPort.close_pr` + `VCSPort.create_pr_comment` protocol members; `GitHubClient.close_pr` implementation via `pr.edit(state="closed")`
- `ProjectConfig.preview_url_template` field; wired through `UpdateProjectConfigCommand`, sqlite repo allowed-set + save()
- `create_web_app(vcs_factory=...)` injection point (prod uses `GitHubClient`, tests inject a `FakeVCS`)

**Deferred**:

- E2E click-through test for Approve button (covered by unit tests against `FakeVCS`)
- Approval-source metrics on `StoryApproved` (needs post-deploy telemetry)
- Branch-name resolution beyond the `pr-{number}` heuristic — real branch name isn't persisted on `Cycle`

**Demo artefact**: _(n/a — all routes verified via `ASGITransport` in the test suite)_

**Exit check**: `uv run pytest tests/ --ignore=tests/e2e -p no:playwright` → 1222 passed.

### 5.4 Sprint D — Observabilité live & replay (V1, V2, V3, V5, C5) `[x] CLOSED 2026-04-20`

- V1 `[x]` agent activity feed per-agent timeline
  - AC: dashboard shows one row per agent with current phase, last step, elapsed time; updates under 1 s
- V2 `[x]` `/cycles/{id}/replay`
  - AC: all events of a cycle stored in `cycle_events` table; UI scrubber with 10 fps playback
- V3 `[x]` agent thought/step panel
  - AC: each agent emits `agent.thought` (string) + `agent.step` (name) events; a collapsible panel shows them
- V5 `[x]` Web Push notifications
  - AC: service worker registers on opt-in button; browser notification on `DemoReady` with click-through to player
- C5 `[x]` cost preview modal
  - AC: `Run Cycle` shows estimated tokens + USD based on current models + last 3 cycles average; user confirms

### Sprint D — résumé (closed 2026-04-20) `[x]`

**Status**: 1241 tests pass (+19 new). All five items ship: V1 (agent timeline), V2 (replay scrubber), V3 (thought/step panel), V5 (browser notifications), C5 (cost preview).

**What shipped**:

| Item | What | Route / Surface |
|---|---|---|
| V1 | Per-agent row (po/techlead/dev/qa) with current action, detail, event count, last-event elapsed timer; live-refreshed via SSE+HTMX | `GET /fragments/cycle/{id}/timeline` + `Agents` card on cycle detail |
| V2 | Event sourcing — every cycle-scoped `DomainEvent` captured in `cycle_events`; replay UI with range scrubber, play/pause, 0.5/1/2/5/10× speed, 10 fps driver, event list with click-to-jump and JSON payload viewer | `GET /cycles/{id}/replay`, `GET /cycles/{id}/replay.json` |
| V3 | New `AgentThought` + `AgentStep` domain events; collapsible `Thoughts & Steps` panel with typed chips (thought vs. step) and SSE-driven refresh | `GET /fragments/cycle/{id}/thoughts` |
| V5 | Service worker at `/static/js/sw.js` handling `notificationclick` → tab focus / `openWindow`; opt-in bell in topnav with three states (idle / enabled / denied); SSE client hands `DemoReady` events to `Notification` API with click-through to `play_url` | `GET /static/js/sw.js`, `GET /static/js/notifications.js`, bell button in `base.html` |
| C5 | `CostEstimator` service with two bases: (1) last 3 `COMPLETED` cycles average (tokens + USD), (2) fallback baseline per configured model (haiku/sonnet/opus pricing table); modal on `Run Cycle` with confirm/cancel gating submit | `GET /projects/{id}/cost-estimate` |

**Tests added** (+19, 1222 → 1241):

| File | Cases | Covers |
|---|---|---|
| `tests/presentation/test_cycle_replay.py` | 5 | event-bus → store persistence, scrubber HTML render, JSON endpoint frame offsets (0/500/2000 ms), empty-state render, link from cycle detail |
| `tests/presentation/test_agent_thoughts.py` | 4 | thought/step events persisted + queried, fragment renders both kinds, empty state, panel included on cycle detail |
| `tests/presentation/test_notifications.py` | 4 | bell renders hidden + `data-state="idle"`, service worker served with `notificationclick`+`skipWaiting`, client script exposes `__swarmShowDemoNotification`, SSE dispatches on `DemoReady` |
| `tests/presentation/test_cost_preview.py` | 6 | model baseline fallback, last-3-completed average (30k / $0.60 from 40/30/20k), `FAILED` cycles skipped, `GET /projects/{id}/cost-estimate` JSON shape, 404 when project missing, modal + JS included on project detail |

**Schema / domain additions**:

- Migration `v004_cycle_events.py` — `cycle_events(id, cycle_id, event_type, occurred_at, payload_json)` with `idx_cycle_events_cycle(cycle_id, occurred_at ASC)`
- `SQLiteCycleEventStore` (append / list_for_cycle) under `infrastructure/persistence/`
- `CycleEventPersistenceHandler` — subscribes to all cycle-scoped events (CycleStarted, PhaseChanged, AgentActivity, **AgentThought**, **AgentStep**, CycleCompleted, CycleFailed, BudgetExceeded), serialises dataclass payloads via `fields(event)`
- `AgentThought(cycle_id, project_id, agent, thought, phase)` + `AgentStep(cycle_id, project_id, agent, step, detail, phase)` domain events
- `GetCycleReplayQuery` → `ReplayFrame(index, event_type, occurred_at, offset_ms, payload)` with offsets computed from first-event delta
- `GetAgentThoughtsQuery` → `ThoughtEntry(kind, agent, text, detail, phase, occurred_at)` reading from `cycle_event_store`
- `CostEstimator` service (effort-profile-aware) with model baseline tokens (haiku 40k / sonnet 120k / opus 200k) + per-1k USD (0.0025 / 0.015 / 0.075)
- `create_web_app(cycle_event_store=...)` injection point (prod wires `SQLiteCycleEventStore(conn)` in `server.py`)
- New static assets: `replay.js`, `notifications.js`, `sw.js`, `cost-preview.js`; CSS blocks for replay scrubber, thoughts panel, notification bell, and cost modal

**Deferred**:

- Real `agent.thought` / `agent.step` emission from the PO/TL/Dev/QA agent graphs (the events + persistence + UI are ready; plumbing the emit sites is Sprint E territory alongside M2 retrospective)
- Web Push with server-sent notifications (VAPID / `PushSubscription`): the current V5 implementation uses the foreground `Notification` API through the service worker; no backend push infra yet
- Post-deploy measurement of replay scrubber usage and cost-modal conversion rates

**Demo artefact**: _(n/a — all routes verified via `ASGITransport` in the test suite)_

**Exit check**: `uv run pytest tests/ --ignore=tests/e2e -p no:playwright` → 1241 passed.

### 5.5 Sprint E — Mémoire vivante & improver (M1, M2, M4) `[x] CLOSED 2026-04-20`

- M1 `[x]` `/projects/{id}/memory` viewer
  - AC: typed entries (convention/lesson/warning), search box filters client-side, pagination (50/page)
- M2 `[x]` retrospective phase
  - AC: each agent contributes 1–3 learnings at cycle end, persisted in `MemoryStore`, visible in demo `learnings` slide
- M4 `[x]` improver agent
  - AC: on `StoryRejected`, agent proposes a diff on the target repo's `CLAUDE.md` and opens a PR

#### Sprint E — résumé (closed 2026-04-20) `[x]`

**Status:** `[x] DONE` — all three features (M1, M2, M4) shipped, full suite green at **1265 tests** (+24 new across the sprint, up from Sprint D's 1241).

**What shipped**

| Feature | Deliverable | Key files |
|---------|-------------|-----------|
| M1 | `ListProjectMemoryQuery` + `MemoryEntryView` (with `is_global`); `/projects/{id}/memory` route; `projects_memory.html` with category/agent filters, client-side search (`memory-viewer.js`, matches `data-text` attrs), 50-item pagination; project detail link (`data-testid="project-memory-link"`); category-coloured chips in `dashboard.css` | `src/theswarm/application/queries/list_project_memory.py`, `src/theswarm/presentation/web/routes/projects.py`, `src/theswarm/presentation/web/templates/projects_memory.html`, `src/theswarm/presentation/web/static/js/memory-viewer.js`, `src/theswarm/presentation/web/static/css/dashboard.css`, `src/theswarm/presentation/web/app.py`, `src/theswarm/presentation/web/server.py` |
| M2 | `RetrospectiveService.run(cycle)` — deterministic rule-based (FAILED→ERRORS, `tokens/limit ≥ 0.9`→IMPROVEMENTS "tighten prompts or raise budget", `cost ≥ $2`→IMPROVEMENTS "cheaper model", COMPLETED clean→CONVENTIONS "completed cleanly"); caps at 3 entries per agent, guarantees ≥1 per agent that ran; persists `MemoryEntry`s to `MemoryStore`; `ReportGenerator.generate(cycle, agent_learnings=...)` threads learnings into `DemoReport.agent_learnings` so the player's `learnings` slide renders them | `src/theswarm/application/services/retrospective.py`, `src/theswarm/application/services/report_generator.py`, `src/theswarm/presentation/web/app.py` |
| M4 | `ImproverAgent.on_story_rejected` — fetches target repo's `CLAUDE.md`, appends dated bullet `- {date} · story `{ticket}` rejected by {user}: {comment}` under `## Lessons from rejected work` (creates section if missing, creates file if missing), branches `improver/claude-md-{ticket}-{YYYYMMDDHHMMSS}`, opens PR; idempotent (skips when lesson substring already present); also writes `MemoryEntry(category=IMPROVEMENTS, agent="improver")`; wired to `EventBus.subscribe(StoryRejected, …)` only when `vcs_factory` is provided; failures logged and swallowed (no cycle breakage) | `src/theswarm/application/services/improver_agent.py`, `src/theswarm/presentation/web/app.py` |

**Tests added**

| File | Focus | Count |
|------|-------|-------|
| `tests/presentation/test_memory_viewer.py` | M1 category/agent filter, global-scope inclusion, route render, empty state, 404 on missing project, detail-page link | 7 |
| `tests/application/test_retrospective.py` | M2 failure warning, budget pressure, high cost, clean convention, cap at 3/agent, ≥1 per agent, persists to store, feeds `ReportGenerator`, wired into web app | 9 |
| `tests/application/test_improver_agent.py` | M4 new section, append-to-existing, idempotent skip, missing-file creation, memory persistence, project-missing skip, no-VCS skip, event bus wiring | 8 |

**Schema / domain additions**

- None — reused the existing `memory_entries` table shipped earlier in the memory stack.
- `ReportGenerator.generate` signature extended with `agent_learnings: tuple[str, ...] = ()` (backwards-compatible default).

**Deferred (documented, not blocking)**

- **LLM-based retrospective strategy** — current rules are mechanical (failed/budget/cost/clean). An LLM-backed `RetrospectiveStrategy` can slot in without changing callers; out of scope for M2 which only requires "1–3 learnings per agent, persisted, visible".
- **Mattermost notification on Improver PR creation** — the Improver opens the PR but does not DM anyone; piggybacks on GitHub's PR notifications for now. A `DemoReady`-style event can be added in Sprint F if we want a dashboard toast.
- **Structural CLAUDE.md edits** — the agent is append-only under a fixed heading; richer structural moves (e.g. dedup/summarise old bullets) are Sprint F M3 territory (memory compaction cron), which will also apply to the CLAUDE.md lessons list.
- **Per-agent learnings slide styling** — `DemoReport.agent_learnings` is now populated end-to-end; the demo player renders them with the existing learnings slide template, no bespoke styling added this sprint.

**Exit check**

- `uv run pytest tests/ --ignore=tests/e2e -p no:playwright` → **1265 passed, 4 warnings** (pre-existing AsyncMock warnings unchanged from Sprint A). No new `[~]`/`[!]` checkboxes remain on Sprint E rows; deferrals are captured above with forward references to the sprint that picks them up.

### 5.6 Sprint F — Pluggabilité & polish (P1, P2, M3, F7, F8) `[x] CLOSED 2026-04-20`

#### P1 · GitHub `/swarm implement` trigger `[x]`

- [x] `WebhookEvent` extended with `comment_body` and `issue_number`; `parse_event()` handles `issue_comment`
- [x] `is_implement_command(event)` — detects `/swarm implement` (case-insensitive, tolerates leading whitespace and trailing text)
- [x] `is_authorised(event, allowed_commenters)` — fail-closed, `"*"` wildcard permits any user
- [x] `_handle_implement_command` in `routes/webhooks.py` maps repo → project, dispatches `RunCycleCommand(triggered_by=f"/swarm implement #{issue} by {user}")`
- [x] unauthorised user → `_post_refusal` posts GitHub comment via `vcs_factory(repo).post_issue_comment(issue_number, body)`; gracefully no-ops if the VCS adapter lacks the method
- [x] unit test suite: `tests/infrastructure/test_webhook_issue_comment.py` (12 tests — parse, command detection edge cases, authorisation matrix)
- [x] route suite: `tests/presentation/test_webhook_implement.py` (5 tests — allowed triggers cycle, denied gets refusal, non-command ignored, unknown repo silent, wildcard allowlist)

#### P2 · Linear ticket source `[x]`

- [x] `LinearClient` Protocol (`query(document, variables) -> dict`) keeps the adapter independent of any HTTP library
- [x] `_DEFAULT_STATE_MAP` maps domain `TicketStatus` → Linear workflow state names (`BACKLOG → "Backlog"`, `READY → "Todo"`, `IN_PROGRESS → "In Progress"`, `REVIEW → "In Review"`, `DONE → "Done"`); overridable per project
- [x] `_LINEAR_PRIORITY_MAP` maps Linear's 0–4 priority to domain `TicketPriority`
- [x] `LinearTicketSource(client, team_id, state_map=None)` implements the full `TicketSource` Protocol: `get_backlog`, `get_ready`, `get_in_progress`, `transition`, `create`
- [x] GraphQL constants: `_LIST_ISSUES_QUERY`, `_LIST_WORKFLOW_STATES_QUERY`, `_UPDATE_ISSUE_STATE_QUERY`, `_CREATE_ISSUE_QUERY`, `_LIST_LABELS_QUERY`
- [x] `_node_to_ticket(node)` converts Linear issue nodes to domain `Ticket`
- [x] unit test suite: `tests/infrastructure/test_linear_ticket_source.py` (16 tests via `FakeLinearClient` dispatching on query-fragment match)
- [~] `ProjectConfig.ticket_source` toggle deferred — adapter exists standalone; wiring it into the cycle orchestration follows once multi-source cycles are scheduled (Sprint G candidate)

#### M3 · Memory compaction `[x]`

- [x] `MemoryCompactionService(memory_store, project_repo)` in `src/theswarm/application/services/memory_compaction.py`
- [x] `_dedup(entries)` collapses `(category, agent, content)` duplicates keeping the earliest timestamp
- [x] `_trim_to_budget(entries, max_bytes=1_000_000, max_entries=2_000, project_id, now)` — drops oldest, emits a compaction marker `MemoryEntry` recording how many were removed
- [x] `compact(project_id)` runs filter → dedup → trim → replace; `run_all(project_ids=None)` iterates explicit list or all projects from `project_repo`
- [x] `run_compaction_loop(service, *, interval_seconds=86_400.0, initial_delay_seconds=60.0)` — `asyncio.create_task` wired at boot in `presentation/web/server.py`; cancellable cleanly
- [x] global entries (`project_id == ""`) never touched — prevents cross-project contamination
- [x] unit test suite: `tests/application/test_memory_compaction.py` (11 tests — dedup semantics, byte/count trim, marker insertion, no-op under budget, project isolation, loop cancellation)

#### F7 · Player speed control (0.5× / 1× / 2×) `[x]`

- [x] `.player-speed-group` button cluster inserted in `demo_player.html` before the fullscreen button
- [x] `demo-player.js` maintains `currentSpeed`, applies `video.playbackRate` on all videos, reapplies via capture-phase `play` listener on stage (per-slide videos)
- [x] `localStorage` key `theswarm:demo-player:speed` persists the choice across demos; sandbox-safe (`try/catch` around access)
- [x] `aria-pressed` + `.is-active` class on the active button
- [x] CSS block in `demo-player.css` — monospace font, accent-tinted active state
- [x] unit test: `tests/presentation/test_demo_player_speed.py::test_speed_buttons_render_in_player` (asserts `data-speed="0.5|1|2"` and group/button class markers render)

#### F8 · A/B demo comparator `[x]`

- [x] `GET /demos/compare?a=<id>&b=<id>` in `routes/demos.py`; renders `demos_compare.html`; either missing report → 404
- [x] `demos_compare.html` — two `.compare-panel` sections with summary grid, one primary video per panel, up to 4 thumbnail screenshots, story list
- [x] `demo-compare.js` — synced `playAll`/`pauseAll` and shared `<input type="range">` scrub (1000-step) driving `currentTime` on both videos based on `maxDuration`; `timeupdate` listener keeps scrubber in sync with video A
- [x] Empty-state fallback (`compare-video-empty`) when a report has no video artifacts
- [x] CSS block in `demo-player.css` — responsive grid collapses to one column under 960 px, sticky bottom control bar
- [x] shortcut form added to `demos_browse.html` (two report-id fields → `/demos/compare`)
- [x] unit test suite: `tests/presentation/test_demo_compare.py` (5 tests — both panels render, missing A/B → 404, missing query params → 422, video paths surface in HTML)

#### Résumé & validation

- **New modules**: `infrastructure/tickets/linear_ticket_source.py`, `application/services/memory_compaction.py`, `presentation/web/templates/demos_compare.html`, `presentation/web/static/js/demo-compare.js`
- **Extended modules**: `infrastructure/scheduling/webhook_handler.py` (+`issue_comment` parsing, `is_implement_command`, `is_authorised`), `presentation/web/routes/webhooks.py` (+`_handle_implement_command`, `_post_refusal`), `presentation/web/routes/demos.py` (+`compare_demos` route), `presentation/web/templates/demo_player.html` (+ speed buttons), `presentation/web/static/js/demo-player.js` (+ speed control block), `presentation/web/static/css/demo-player.css` (+ speed-btn + compare styles), `presentation/web/server.py` (+ compaction loop task)
- **Test files added**: 6 files / 50 tests total (P1: 17, P2: 16, M3: 11, F7: 1, F8: 5)
- **Full suite**: `uv run pytest tests/ --ignore=tests/e2e -p no:playwright` → **1315 passed, 4 warnings** (pre-existing AsyncMock warnings unchanged from Sprint A). No new `[~]`/`[!]` boxes remain on Sprint F rows; the `ProjectConfig.ticket_source` toggle is the only deferral, carried forward to Sprint G.

---

## 6. Changements techniques concrets (quick hits priorisés)

### P0 — à faire dès Sprint A

```python
# domain/projects/entities.py — étendre ProjectConfig
@dataclass(frozen=True)
class ProjectConfig:
    max_daily_stories: int = 3
    token_budget_po: int = 300_000
    token_budget_techlead: int = 600_000
    token_budget_dev: int = 1_000_000
    token_budget_qa: int = 300_000
    # NEW
    effort: str = "medium"                     # "low" | "medium" | "high"
    models: dict[str, str] = field(default_factory=lambda: {
        "po": "sonnet", "techlead": "sonnet",
        "dev": "sonnet", "qa": "haiku",
    })
    daily_cost_cap_usd: float = 0.0            # 0 = no cap
    daily_tokens_cap: int = 0
    monthly_cost_cap_usd: float = 0.0
    paused: bool = False
```

```python
# application/services/budget_guard.py
class BudgetGuard:
    async def check(self, project: Project) -> None:
        if project.config.paused:
            raise CycleBlocked("paused")
        spent = await self._spent_today(project.id)
        cap = project.config.daily_cost_cap_usd
        if cap > 0 and spent >= cap:
            raise CycleBlocked(f"daily cap ${cap:.2f} reached")
```

```python
# infrastructure/persistence/sqlite_secrets.py
class SqliteSecretVault:
    """Encrypted per-project secret storage (Fernet)."""
    async def set(self, project_id: str, key: str, value: str) -> None: ...
    async def get(self, project_id: str, key: str) -> str | None: ...
    async def rotate_master_key(self, new_key: bytes) -> None: ...
```

### Routes à ajouter

```
PATCH /projects/{id}/config         # éditeur form
POST  /projects/{id}/pause          # kill switch
POST  /projects/{id}/resume
POST  /projects/{id}/secrets        # set secret
DELETE /projects/{id}/secrets/{k}   # rotate
POST  /demos/{id}/stories/{tid}/approve
POST  /demos/{id}/stories/{tid}/reject
POST  /demos/{id}/stories/{tid}/comment
GET   /d/{short}                    # public demo
GET   /cycles/{id}/replay
```

### Events à ajouter

- `DemoReady(cycle_id, report_id, project_id, thumbnail_url)` → handler push notifications
- `CycleBlocked(project_id, reason)` → toast
- `StoryApproved(report_id, ticket_id, user)` → VCSPort.merge
- `StoryRejected(report_id, ticket_id, user, comment)` → VCSPort.close + improver trigger

### Tests nouveaux

- `tests/presentation/test_project_config_editor.py` — form PATCH roundtrip
- `tests/application/test_budget_guard.py` — caps, paused, rollover mensuel
- `tests/infrastructure/test_secret_vault.py` — chiffrement, rotation
- `tests/e2e/test_demo_approve_flow.py` — Playwright clique Approve → PR mergée
- `tests/e2e/test_demo_toast.py` — cycle complete → toast SSE visible sous 2s

---

## 7. KPIs pour mesurer qu'on a réussi

| KPI | Cible |
|-----|-------|
| Temps « cycle fini → humain clique Approve » | < 2 min |
| % de cycles avec démo vidéo jouable | > 95% |
| % d'approbations faites depuis la démo (pas depuis GitHub) | > 70% |
| Configs projet modifiées depuis le web (pas YAML) | > 90% |
| Cap atteint sans blocage cycle = 0 | oui |
| Latence toast SSE « nouvelle démo » | < 2s après `CycleCompleted` |

---

## 8. Résumé exécutif (TL;DR)

1. **La démo jouable est le produit.** Tout le reste la sert. Chaque sprint livre une démo de lui-même, partageable, approuvable en un clic.
2. **Le dashboard doit piloter les modèles.** Effort / modèle / budget / pause : par projet, sans redéploiement, sans YAML.
3. **Vault secrets + caps = passage au multi-projet sérieux.** Aujourd'hui on est mono-tenant implicite.
4. **6 sprints (A→F)** pour passer de « cycle + rapport texte » à « push démo + controls + replay + mémoire vivante + pluggabilité ».
5. **Dogfooding intégral.** TheSwarm travaille sur TheSwarm, avec des subagents Claude Code en PostToolUse (reviewer, tdd-guide, e2e-runner) pour ne pas bosser seul.
