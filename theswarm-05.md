# TheSwarm — Plan 05 : Résilience, État, Observabilité

**Date :** 2026-04-20
**Auteur :** revue post-sprint-F (tout livré `[x]`) + diagnostic production (`bots.jrec.fr/swarm`) + exploration architecturale (Explore agent) + re-lecture `config.py`, `api.py`, `agents/qa.py`, `cycle.py`, `gateway/wiring.py`.

**Nord magnétique** : après A→F on a une vitrine jouable et pilotable. Reste à **survivre en production** : si un cycle plante à la phase QA, on doit pouvoir le reprendre ; si un modèle est lent, on doit le savoir ; si deux projets apprennent la même leçon, ils doivent se la partager.

---

## 1. Où on en est après Sprints A→F

### Livré (2026-04)

| Axe | État | Preuve |
|-----|------|--------|
| Démo jouable first-class (F1-F9) | ✅ | Toast SSE + DM + player + approve/reject + live preview + share slug + A/B + speed |
| Controls par projet (C1-C6) | ✅ | `ProjectConfig` editor + effort slider + Fernet vault + caps + pause + cost preview |
| Visibilité live (V1-V5) | ✅ | Agent timeline + replay scrubber + thought panel + Web Push |
| Mémoire (M1-M4) | ✅ | Viewer + retrospective + compaction cron + improver agent |
| Pluggabilité (P1-P2) | ✅ | GitHub `/swarm implement` + Linear adapter |
| Dogfooding | ✅ | `seed-self` + 6 démos sprint A→F sur le dashboard prod |

### Déployé en prod (`bots.jrec.fr/swarm`)

- 1125+ tests verts
- Cert Let's Encrypt (résolveur `le`, pas `letsencrypt`)
- Volume persistant `/home/debian/swarm-data` monté en `/home/botuser/.swarm-data`
- CSS design-system finalisé (formulaires globaux stylés dark)
- `docs/demos/sprint-A.webm` joué correctement ; sprints B-F ont page démo sans vidéo (pas encore enregistrés)

### Dette visible post-F

| Dette | Impact | Quoi faire |
|-------|--------|-----------|
| `AgentState` TypedDict 25+ champs mutables | Couplage fort, tests fragiles, impossible à type-checker strictement | Décomposer en DTOs frozen par phase (PO/TL/Dev/QA) |
| Pas de checkpoint de cycle | Un crash à la phase QA = tout perdre, pas de reprise | Persister `Cycle` après chaque phase + bouton Resume |
| QA = un node monolithique (`qa.py` 900+ lignes) | Impossible de rejouer uniquement le replay vidéo sans retourner semgrep+tests | Éclater en sous-agents `TestWriter`, `TestRunner`, `SecurityScanner`, `DemoRecorder` |
| Claude API sans timeout adaptatif | Une latence Anthropic de 3min fige le cycle | Timeout par modèle + exponential backoff |
| Aucun budget GitHub API observable | Rate limits silencieux, erreurs surprises | Compteur + circuit-breaker sur PyGithub |
| Mémoires projet **cloisonnées** | Sprint A de `repo-X` ne profite pas des leçons de `repo-Y` | Mémoire globale partagée lue avant chaque phase |
| Pas de traces distribuées | Debug d'un cycle = grep dans Seq + relire replay | OpenTelemetry sur les phases |
| Prompts hardcodés | A/B testing impossible, pas de versionnage | Prompt registry + MLflow-like tracking |
| Un seul provider LLM (Anthropic) | Pas de fallback, pas de routing par coût | Port `LLMPort` + adapters OpenAI/local |
| Sprints B-F sans vidéo | Démo dashboard incomplète | Enregistrement QA → auto-backfill docs/demos |

---

## 2. Ce que fait la concurrence (avril 2026)

| Produit | Nouveauté post-Q1 2026 | Ce qu'on peut voler |
|---------|------------------------|---------------------|
| **Devin 2** | Team mode : multiple droids partagent un contexte | **Shared memory bank** entre projets |
| **Factory Droids** | Budget adaptatif (reroute Sonnet → Opus si stagnation détectée) | **Cost-aware model routing** à chaque phase |
| **OpenHands** | Event store append-only + replay déterministe | **Event sourcing** pour le cycle (on a déjà `cycle_events`, pousser plus loin) |
| **Sweep AI** | Prompt A/B testing avec rollout % | **Prompt registry** + feature flags sur prompts |
| **GH Copilot Workspace** | Plan éditable **pendant** le run (intervention live) | **Live steering** : humain peut injecter une note au dev agent en cours |
| **Cursor Composer 2** | Inline diff review avec hunk-by-hunk accept/reject | Déjà en démo player ; porter au niveau PR **pendant** review TechLead |
| **Replit Agent 2** | Preview multi-frame (desktop / mobile / tablet) | Extension naturelle de `preview_url_template` |
| **Bolt.new** | Partage collaboratif live (deux humains sur une même session) | Pour plus tard ; nécessite CRDT |
| **Warp Agents** | Steering par commentaire comme un sénior dirige un junior | **Live agent steering** via Mattermost DM |

**Ce qui reste notre edge unique** :

1. **Démo jouable en slideshow** (title → story → before/after → vidéo → gates → learnings) — personne ne fait ça.
2. **Controls par projet** (effort, caps, secrets, pause) éditables depuis l'UI — Factory s'en approche mais reste CLI-heavy.
3. **Replay scrubber 10fps** du cycle entier avec reconstruction des états agents.
4. **Share slug public** `/d/<hash>` read-only — marketing ready.

**Ce que personne n'a et serait notre prochain edge** :

1. **Cross-project memory** : un bug fixé sur `repo-A` informe `repo-B` automatiquement.
2. **Cycle checkpoint/resume** : reprendre un cycle planté depuis la dernière phase réussie.
3. **Self-improvement mesurable** : chaque sprint livre un delta measurable (tokens/cycle, stories/cycle, approve rate).

---

## 3. Propositions de nouvelles fonctionnalités

Priorités P0 (survie) → P3 (nice-to-have).

### 3.1 Résilience (LE point principal de ce plan)

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| G1 | **Checkpoint de cycle après chaque phase** | P0 | Persister `Cycle.phase_states[phase] = serialized_state` en SQLite ; si crash, `Resume` reprend à la phase suivante |
| G2 | **Timeout adaptatif Claude API** | P0 | Par modèle/phase : Haiku 30s, Sonnet 90s, Opus 300s. Exponential backoff `2^n` jusqu'à 3 retries puis fail la phase. Métrique `claude_latency_p95` |
| G3 | **Circuit-breaker GitHub API** | P0 | Compteur rate-limit depuis `GitHub.get_rate_limit()`, bloque PR/review si reste < 100, attend reset avec toast SSE `⏸ GitHub rate limit — reprise dans Xmin` |
| G4 | **Watchdog QA server readiness** | P1 | Avant `PlaywrightRecorder.start()`, poll `GET /` pendant 30s ; si timeout, skip recording slide avec `skipped=true` au lieu de crasher |
| G5 | **Cycle Resume UI** | P1 | Dans `/cycles/{id}`, bouton `↻ Resume from <phase>` si `status=failed` ; réutilise `phase_states[<last_ok>]` |

### 3.2 État agents — hygiène structurelle

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| H1 | **DTOs Pydantic par phase** | P0 | `POState`, `TechLeadState`, `DevState`, `QAState` frozen ; `AgentState` devient `Union` discriminée ; validation à l'entrée de chaque node |
| H2 | **Éclater QA en 4 sous-agents** | P0 | `TestWriterAgent` (génère E2E) → `TestRunnerAgent` (pytest+playwright) → `SecurityScannerAgent` (semgrep+bandit) → `DemoRecorderAgent` (playwright record). Chaque sous-agent a son node LangGraph rejouable |
| H3 | **Port `LLMPort` abstrait** | P1 | `AnthropicAdapter` + stub `OpenAIAdapter` + `LocalAdapter` (vLLM). Switch via `ProjectConfig.llm_provider`. Enables fallback si provider down |
| H4 | **Tests contractuels par agent** | P1 | `tests/agents/test_po_contract.py` — valide que `PO` produit un `POState` valide pour toute entrée conforme ; idem TL/Dev/QA |

### 3.3 Observabilité — traces et coûts

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| I1 | **OpenTelemetry traces par cycle** | P0 | `opentelemetry-api` + exporter OTLP → Jaeger/Tempo ; span par phase/node, liens vers Seq logs. Replay viewer affiche la trace au-dessus du scrubber |
| I2 | **Prometheus histograms par phase** | P0 | `theswarm_phase_duration_seconds{phase,agent,model}` ; `theswarm_phase_tokens{phase,model}` ; grafana dashboard préconfiguré dans `docs/grafana/` |
| I3 | **Mattermost alerting sur anomalies** | P1 | Règle : p95 phase > baseline × 2 → DM aux admins ; cap atteint → DM au project owner ; resume nécessaire → DM avec lien |
| I4 | **Cost preview dashboard projet** | P1 | `/projects/{id}/costs` : courbe 30j, breakdown par phase/modèle, projection fin de mois vs cap |

### 3.4 Intelligence inter-projets

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| J1 | **Shared memory bank** cross-project | P1 | `global_memory` table + `MemoryScope.GLOBAL\|PROJECT` ; chaque agent lit global + project avant action ; entries marquées `source_project` |
| J2 | **Similar story prefill** | P2 | Au démarrage d'un cycle, embeddings (sentence-transformers) des stories → top-3 stories similaires des autres projets affichées au TL |
| J3 | **Disagreement resolver** | P2 | Si deux mémoires contradictoires (`always use X` vs `never use X`), un agent `arbiter` lit le contexte et marque une comme `deprecated` |
| J4 | **Drift-aware merging** | P3 | Avant merge PR, check si autre projet a ouvert/mergé un PR touchant le même fichier de dep (e.g. `fastapi==0.x`) ; warn si oui |

### 3.5 Human-in-the-loop live

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| K1 | **Live agent steering** via Mattermost | P1 | DM `@swarm-dev hint: use async` pendant le run → injecté dans le prompt du prochain appel Claude. Affiché dans `_agent_thoughts.html` |
| K2 | **Ticket drafting in dashboard** | P1 | `/projects/{id}/tickets/new` : formulaire qui crée issue GitHub/Linear sans ouvrir le site. Preview `gh issue create` côté humain |
| K3 | **Diff-level review during TL phase** | P2 | Pendant review_loop, dashboard affiche le diff hunk-par-hunk ; humain peut commenter une ligne → commentaire injecté dans prompt TL |
| K4 | **Replay scrubber v2** | P2 | Ajouter annotations humaines posables sur la timeline + export d'un clip GIF pour partager un moment précis |

### 3.6 Auto-amélioration mesurable

| # | Fonction | Prio | Résumé |
|---|----------|------|--------|
| L1 | **Improver agent → CLAUDE.md PR** étendu | P1 | Déjà en place ; étendre aux prompts système agents, pas seulement CLAUDE.md. Review humaine obligatoire sur PR meta |
| L2 | **Prompt A/B testing** | P2 | `prompt_registry` avec variantes ; 50/50 par projet pendant N cycles ; `RunMetric.approve_rate` compare ; promote gagnant |
| L3 | **Cost-aware model routing** | P2 | `ModelRouter` : si baseline d'un projet montre que Sonnet suffit pour `dev`, downgrade auto depuis Opus ; upgrade si `max_dev_retries` atteint 2x consécutifs |
| L4 | **Public demo gallery polish** | P2 | `/gallery` agrégant les `/d/<short>` publics avec filtres (projet, tag, date) ; OG tags pour preview Twitter/LinkedIn |
| L5 | **Self-recording per feature** | P3 | Chaque fois qu'un PR merge une feature avec tag `demo:required`, un cycle QA auto enregistre `docs/demos/<slug>.webm` puis commit via PR séparée |

---

## 4. Comment les agents accélèrent ce plan

Après A→F on a la boucle complète. Ce plan **se dogfood à 100%**.

| Levier | Comment |
|--------|---------|
| **seed-self par sprint** | Chaque sprint G-L ajoute une entrée `_SPRINTS` dans `self_seed.py`, enregistre sa vidéo, apparaît en démo sur le dashboard |
| **Agents spécialisés** | `architect` pour H1-H2 (DDD cleanup), `python-reviewer` PostToolUse, `tdd-guide` sur chaque feature G/H/I, `performance-optimizer` pour I2, `security-reviewer` pour G3/H2 |
| **Parallel tracks** | Sprints G (résilience) et I (observabilité) indépendants de H (state cleanup) et J (cross-project) ; 2-3 agents en parallèle |
| **docs-lookup** | OpenTelemetry Python SDK, Fernet rotation, Pydantic v2 discriminated unions, Sentence-Transformers via Context7 |
| **Continuous learning** | J1 (shared memory) rend chaque sprint plus rapide que le précédent |

**Règle stricte** : chaque sprint livre 1 vidéo démo commitée en `docs/demos/sprint-<X>.webm` + entrée `_SPRINTS`. Pas de démo = pas de sprint fermé.

---

## 5. Plan d'exécution — 6 sprints (G → L)

Chaque sprint = 2 semaines de dev humain ou ~5 cycles agent. Ordre = sévérité de la douleur (résilience avant features flashy).

### 5.0 Progress tracker

**Legend** : `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

| Sprint | Feature | Status | Owner | Notes |
|--------|---------|--------|-------|-------|
| G | G1 · Cycle checkpoint after each phase | `[ ]` | — | Persist `phase_states` in SQLite, enable Resume |
| G | G2 · Adaptive Claude timeout + backoff | `[ ]` | — | Per-model timeouts, exponential retry |
| G | G3 · GitHub rate-limit circuit breaker | `[ ]` | — | Block before exhaustion, SSE toast |
| G | G4 · QA server readiness watchdog | `[ ]` | — | Poll before Playwright, skip gracefully |
| G | G5 · Cycle Resume UI | `[ ]` | — | Dashboard button, reuses G1 checkpoints |
| H | H1 · Pydantic AgentState per phase | `[ ]` | — | Frozen DTOs, discriminated union |
| H | H2 · Split QA into 4 sub-agents | `[ ]` | — | TestWriter/Runner/Security/Recorder |
| H | H3 · LLM port abstraction | `[ ]` | — | Anthropic + OpenAI + local adapters |
| H | H4 · Per-agent contract tests | `[ ]` | — | Validates DTOs, enables refactoring |
| I | I1 · OpenTelemetry traces | `[ ]` | — | Spans per phase, OTLP exporter |
| I | I2 · Prometheus phase histograms | `[ ]` | — | Duration + token metrics |
| I | I3 · Mattermost anomaly alerting | `[ ]` | — | p95 drift, cap reached, resume needed |
| I | I4 · Cost preview dashboard per project | `[ ]` | — | 30-day curve, end-of-month projection |
| J | J1 · Shared memory bank | `[ ]` | — | `MemoryScope.GLOBAL`, cross-project reads |
| J | J2 · Similar story prefill | `[ ]` | — | sentence-transformers embeddings |
| J | J3 · Disagreement resolver | `[ ]` | — | Arbiter agent on contradictory entries |
| J | J4 · Drift-aware merging | `[ ]` | — | Cross-project dep-file collision warn |
| K | K1 · Live agent steering | `[ ]` | — | Mattermost DM → prompt injection |
| K | K2 · Ticket drafting in dashboard | `[ ]` | — | Form creates GitHub/Linear issue |
| K | K3 · Diff-level review hunks | `[ ]` | — | TL phase inline comments |
| K | K4 · Replay scrubber v2 | `[ ]` | — | Annotations, GIF export |
| L | L1 · Improver extends to system prompts | `[ ]` | — | Not just CLAUDE.md, review-gated |
| L | L2 · Prompt A/B testing | `[ ]` | — | Registry + variant rollout |
| L | L3 · Cost-aware model routing | `[ ]` | — | Auto up/downgrade from baseline |
| L | L4 · Public demo gallery | `[ ]` | — | `/gallery` aggregator + OG tags |
| L | L5 · Self-recording per feature | `[ ]` | — | `demo:required` tag → auto webm PR |

### 5.1 Sprint G — Résilience production (G1-G5) `[ ] OPEN`

#### G1 · Cycle checkpoint after each phase

- [ ] `domain/cycles/checkpoint.py` : `PhaseCheckpoint(phase, state_json, completed_at, ok)` frozen dataclass
- [ ] `infrastructure/persistence/sqlite_repos.py` : table `cycle_checkpoints(cycle_id, phase, state_json, ok, ts)`
- [ ] `cycle.py` : après chaque node (PO / TL breakdown / Dev iter / TL review / QA), `await checkpoint_repo.save(PhaseCheckpoint(...))`
- [ ] serialization via `model_dump_json()` (post-H1) ; avant H1 : `json.dumps` strict des fields pickable
- [ ] test : crash simulé en phase QA, checkpoint des 4 phases précédentes présent en DB

#### G2 · Adaptive Claude timeout + backoff

- [ ] `tools/claude.py` : `ClaudeCLI.call(model, prompt, timeout=None)` ; timeout par défaut selon modèle (Haiku=30, Sonnet=90, Opus=300)
- [ ] wrapper `tenacity` : 3 retries, `wait_exponential(min=2, max=30)`, retry seulement sur `APITimeoutError`/`RateLimitError`
- [ ] métrique `claude_call_duration_seconds{model,phase}` histogram
- [ ] test : mock `AsyncAnthropic` qui timeout → 3 retries → raise `PhaseTimeoutError`
- [ ] logs Seq avec `claude.latency_ms`, `claude.retries`, `claude.model`

#### G3 · GitHub rate-limit circuit breaker

- [ ] `tools/github.py` : `GitHub._check_rate_limit()` avant chaque batch d'appels (open PR, list issues)
- [ ] si `remaining < 100` ET `reset_in > 60s` → raise `GitHubRateLimitBlocked(reset_at)`
- [ ] `cycle.py` : catche cette exception, émet `CycleBlocked(reason="github_rate_limit", resume_at=...)`, attend `reset_at + 10s`
- [ ] SSE toast `⏸ GitHub rate limit — resuming at HH:MM`
- [ ] test : mock `get_rate_limit()` retourne `remaining=50` → handler bloque correctement

#### G4 · QA server readiness watchdog

- [ ] `infrastructure/recording/playwright_recorder.py` : `wait_for_url(url, timeout=30) -> bool` avec `httpx.AsyncClient`
- [ ] `agents/qa.py` : `capture_screenshots` node appelle `wait_for_url` ; si False → `state["qa_recording_skipped"] = True`, log warning, continue
- [ ] `generate_demo_report` : si `qa_recording_skipped` vrai, slide `screenshots` montre placeholder `⚠ Preview unavailable` au lieu de crash
- [ ] test : mock `httpx.get` timeout → capture skipped, pas d'exception propagée

#### G5 · Cycle Resume UI

- [ ] query `GetCycleCheckpointsQuery(cycle_id) -> list[PhaseCheckpoint]`
- [ ] route `POST /cycles/{id}/resume` : load last `ok=True` checkpoint, replay from next phase
- [ ] template `cycles.html` : si `cycle.status == "failed"` ET checkpoints existent, bouton `↻ Resume from <phase>` + badge `Failed at <phase>`
- [ ] audit log entry `cycle_resumed_by={user}`
- [ ] test : crée cycle avec 3 checkpoints ok + 1 failed → resume repart de la 4e phase

### 5.2 Sprint H — Hygiène état agents (H1-H4) `[ ] OPEN`

#### H1 · Pydantic AgentState per phase

- [ ] `config.py` : remplacer `AgentState` TypedDict par discriminated union
- [ ] `POState(BaseModel, frozen=True)` : `project_id`, `backlog_issues`, `daily_plan`, `selected_stories`
- [ ] `TechLeadState(BaseModel, frozen=True)` : `po_state`, `breakdown`, `dev_tasks`, `review_results`
- [ ] `DevState(BaseModel, frozen=True)` : `tl_state`, `current_task`, `iterations`, `pr_opened`
- [ ] `QAState(BaseModel, frozen=True)` : `dev_state`, `merged_prs`, `test_results`, `artifacts`, `gates`
- [ ] `AgentState = POState | TechLeadState | DevState | QAState` avec `Field(discriminator="phase")`
- [ ] migration : chaque node d'agent prend/renvoie son DTO spécifique ; LangGraph state passe via `Union`
- [ ] test : contrat strict — si un node renvoie un champ extra, ValidationError

#### H2 · Split QA into 4 sub-agents

- [ ] `agents/qa/test_writer.py` — génère tests E2E via Claude ; in: `QAState.merged_prs`, out: `generated_tests`
- [ ] `agents/qa/test_runner.py` — pytest + playwright ; in: tests, out: `test_results`
- [ ] `agents/qa/security_scanner.py` — semgrep + bandit ; in: repo, out: `security_findings`
- [ ] `agents/qa/demo_recorder.py` — before/after, walkthrough video, thumbnail ; in: stories + URLs, out: `artifacts`
- [ ] `agents/qa/__init__.py` — compile_graph chaîne les 4 sous-agents, preserves public API `qa_graph`
- [ ] tests per sub-agent (mock les voisins)
- [ ] replay : chaque sous-agent peut être relancé seul depuis checkpoint

#### H3 · LLM port abstraction

- [ ] `domain/llm/port.py` : `class LLMPort(Protocol)` avec `async def call(model, prompt, **kwargs) -> str`
- [ ] `infrastructure/llm/anthropic_adapter.py` — wraps `ClaudeCLI` existant
- [ ] `infrastructure/llm/openai_adapter.py` — stub initial, wire if `OPENAI_API_KEY` set
- [ ] `infrastructure/llm/local_adapter.py` — stub pour futur vLLM
- [ ] `ProjectConfig.llm_provider: Literal["anthropic", "openai", "local"] = "anthropic"`
- [ ] `dependencies.py` : résout l'adapter au démarrage par projet
- [ ] test : run `po_graph` avec stub adapter → comportement identique

#### H4 · Per-agent contract tests

- [ ] `tests/agents/test_po_contract.py` : property-based (hypothesis) → `POState` valide en entrée produit état valide en sortie
- [ ] idem TL / Dev / QA
- [ ] `tests/agents/test_no_state_leakage.py` : vérifie qu'aucun champ de `TechLeadState` ne fuit en `DevState`
- [ ] CI : fail si contrat cassé

### 5.3 Sprint I — Observabilité (I1-I4) `[ ] OPEN`

#### I1 · OpenTelemetry traces per cycle

- [ ] deps : `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`
- [ ] `infrastructure/tracing/tracer.py` : init provider, resource `service.name=theswarm`
- [ ] span parent par cycle `cycle.{id}` ; spans enfants par phase (`po`, `techlead.breakdown`, `dev.iter.{n}`, `qa.record`)
- [ ] trace_id injecté dans logs Seq (field `trace_id`)
- [ ] replay page : si `OTEL_EXPORTER_OTLP_ENDPOINT` set, lien `↗ Trace` vers Jaeger UI
- [ ] docker-compose : service Jaeger optionnel

#### I2 · Prometheus phase histograms

- [ ] `presentation/web/metrics.py` : `phase_duration = Histogram("theswarm_phase_duration_seconds", ["phase", "agent", "model"])`
- [ ] `phase_tokens = Counter("theswarm_phase_tokens_total", ["phase", "model", "kind=input|output"])`
- [ ] wrap chaque node avec context manager qui observe
- [ ] `docs/grafana/theswarm-overview.json` dashboard : p50/p95/p99 par phase, tokens par jour
- [ ] test : après un stub cycle, `/metrics` contient des samples non-zéro

#### I3 · Mattermost anomaly alerting

- [ ] `application/services/anomaly_detector.py` : au `CycleCompleted`, compare durations aux baselines (last 10 cycles même phase)
- [ ] rule : `p95 > baseline * 2` → émet `AnomalyDetected(phase, factor)`
- [ ] handler gateway DM admins (`SWARM_ADMIN_USER_IDS` comma-separated)
- [ ] rule `CapReached` : DM au project owner
- [ ] rule `ResumeNeeded` : DM avec lien vers `/cycles/{id}`
- [ ] test : baseline mock + cycle lent → DM envoyé

#### I4 · Cost preview dashboard per project

- [ ] `application/queries/get_project_costs.py` : agrège `phase_tokens` sur 30j via `cycle_events` + prix par modèle
- [ ] route `GET /projects/{id}/costs` + template `project_costs.html`
- [ ] courbe Chart.js (30j), breakdown par phase/modèle, projection fin de mois
- [ ] warning si projection > `monthly_cost_cap_usd * 0.9`
- [ ] test : insère cycles fake → endpoint retourne coûts agrégés corrects

### 5.4 Sprint J — Intelligence inter-projets (J1-J4) `[ ] OPEN`

#### J1 · Shared memory bank

- [ ] `domain/memory/scope.py` : `class MemoryScope(Enum): GLOBAL, PROJECT`
- [ ] `domain/memory/entry.py` : add `scope: MemoryScope`, `source_project_id: str | None`
- [ ] table `memory_entries` : add columns `scope TEXT NOT NULL`, `source_project_id TEXT NULL`
- [ ] `MemoryStore.list_for_agent(project_id)` lit `scope=GLOBAL` + `scope=PROJECT AND project_id=?`
- [ ] UI : sur `/projects/{id}/memory`, filtre `All / Project / Global`, bouton `↑ Promote to global`
- [ ] test : entry promue lue par un autre projet

#### J2 · Similar story prefill

- [ ] deps : `sentence-transformers` (all-MiniLM-L6-v2, ~90MB, CPU OK)
- [ ] `infrastructure/embeddings/embedder.py` : cache d'embeddings par story
- [ ] au démarrage cycle : embed selected_stories, top-3 plus proches cross-project via cosine
- [ ] panel UI `similar stories` dans `/cycles/{id}/live` avec liens vers démos passées
- [ ] fallback : si `sentence-transformers` absent, skip silencieusement
- [ ] test : 2 stories quasi identiques de projets différents → proximité > 0.8

#### J3 · Disagreement resolver

- [ ] `application/services/memory_arbiter.py` : détecte paires d'entries contradictoires (regex + LLM)
- [ ] si trouvé, marque la plus ancienne `deprecated=True` et logge l'arbitrage
- [ ] UI : badge `⚠ deprecated` + lien `why` vers le log
- [ ] exécuté dans `memory_compaction_loop` déjà planifié
- [ ] test : 2 entries `always X` / `never X` → plus vieille dépréciée

#### J4 · Drift-aware merging

- [ ] `infrastructure/vcs/dep_watcher.py` : diff des fichiers `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`
- [ ] avant merge PR : check autres projets ont touché les mêmes deps dans la 24h
- [ ] si oui, SSE toast `⚠ dep drift: project X changed fastapi yesterday` ; TL doit confirmer
- [ ] test : mock 2 PRs sur fastapi dans 2 projets → warning émis

### 5.5 Sprint K — Human-in-the-loop live (K1-K4) `[ ] OPEN`

#### K1 · Live agent steering via Mattermost

- [ ] `gateway/wiring.py` : handler DM `@swarm-<agent> hint: <text>`
- [ ] push dans `cycle_state.pending_hints[agent_name]`
- [ ] dans node Claude call : prepend `[USER HINT: ...]` au prompt avant invoke
- [ ] UI : `_agent_thoughts.html` affiche hints actifs avec author+ts
- [ ] test : DM pendant cycle → hint présent dans prochain prompt observé

#### K2 · Ticket drafting in dashboard

- [ ] `presentation/web/routes/tickets.py` : `GET /projects/{id}/tickets/new` + `POST`
- [ ] formulaire HTMX : titre, body, labels, ticket_source (GitHub/Linear)
- [ ] preview avant submit (render markdown)
- [ ] crée via `TicketPort.create(title, body, labels)`
- [ ] test : submit → issue créée via stub TicketPort

#### K3 · Diff-level review during TL phase

- [ ] pendant `review_loop`, `cycle_events` émet `DiffHunkReviewable(pr, hunks)`
- [ ] template `review_live.html` : render diff via `unidiff` + boutons `💬 Comment` par hunk
- [ ] humain commente → event `HumanReviewHint(pr, hunk_id, text)` → injecté dans prompt TL
- [ ] test : commentaire posté pendant review → TL voit le hint

#### K4 · Replay scrubber v2

- [ ] `domain/cycles/annotation.py` : `CycleAnnotation(cycle_id, timestamp_ms, author, text)`
- [ ] UI scrubber : clic droit → popup `Add note`, stockée et rendue comme marker
- [ ] bouton `Export GIF` : ffmpeg entre deux markers, save sous `~/.swarm-data/clips/`
- [ ] test : annotation persistée et affichée au reload

### 5.6 Sprint L — Auto-amélioration (L1-L5) `[ ] OPEN`

#### L1 · Improver extends to system prompts

- [ ] `ImproverAgent.on_story_rejected` : si feedback pattern connu (regex), propose edit dans `agents/<role>/prompts.py` au lieu de `CLAUDE.md`
- [ ] PR meta marquée `meta:prompt-update`, label auto, blocked sans 2 approvals
- [ ] rollback trivial (revert commit)
- [ ] test : reject avec pattern `always use async` → PR sur `dev/prompts.py` créé

#### L2 · Prompt A/B testing

- [ ] `domain/prompts/registry.py` : `PromptRegistry` avec variantes, `active_rollout_pct`
- [ ] `RunMetric(cycle_id, variant, approve_rate, duration, tokens)`
- [ ] après N cycles/variant, stats Z-test ; si sig. meilleur, promote
- [ ] UI `/prompts` : liste variantes, rollout slider, historique perf
- [ ] test : 10 cycles chacun sur A/B → promote le meilleur

#### L3 · Cost-aware model routing

- [ ] `application/services/model_router.py` : input `(phase, project_id, baseline_success_rate)`, output `model`
- [ ] règle : si `approve_rate_sonnet_last_20 > 0.85` sur `dev` → downgrade Opus→Sonnet
- [ ] upgrade si `max_dev_retries` atteint 2 cycles consécutifs
- [ ] `ProjectConfig.auto_routing: bool = False` (opt-in)
- [ ] test : fake baselines → routing cohérent

#### L4 · Public demo gallery

- [ ] `presentation/web/routes/gallery.py` : `GET /gallery` agrège tous les rapports avec `share_slug` non-null
- [ ] filtres : projet, tag, date ; tri par récent/popularité (hit count)
- [ ] OG tags `og:image=<thumbnail>`, `og:video=<webm>`, pour preview Twitter/LinkedIn
- [ ] sitemap.xml pour SEO
- [ ] test : 3 démos publiques → gallery affiche, OG scrapable

#### L5 · Self-recording per feature

- [ ] `PostMergeHook` écoute les `CycleCompleted` ; si PR avait label `demo:required`
- [ ] spawne cycle QA-only sur la feature → enregistre `docs/demos/<slug>.webm`
- [ ] ouvre PR séparée sur le même repo avec la vidéo
- [ ] update `self_seed._SPRINTS` via `AUTO-GENERATED` bloc
- [ ] test : simule merge avec tag → fichier apparait + PR ouverte

---

## 6. Changements structurels (code)

### Nouveaux ports / adapters

```python
# domain/llm/port.py
class LLMPort(Protocol):
    async def call(self, model: str, prompt: str, **kwargs) -> str: ...

# domain/memory/scope.py
class MemoryScope(Enum):
    GLOBAL = "global"
    PROJECT = "project"

# domain/cycles/checkpoint.py
@dataclass(frozen=True)
class PhaseCheckpoint:
    cycle_id: str
    phase: str
    state_json: str
    ok: bool
    completed_at: datetime
```

### Décomposition de `AgentState`

```python
# config.py (after H1)
class POState(BaseModel, frozen=True):
    phase: Literal["po"] = "po"
    project_id: str
    backlog_issues: tuple[Issue, ...]
    daily_plan: str

class TechLeadState(BaseModel, frozen=True):
    phase: Literal["techlead"] = "techlead"
    po_state: POState
    breakdown: tuple[DevTask, ...]
    # ...

AgentState = Annotated[
    POState | TechLeadState | DevState | QAState,
    Field(discriminator="phase"),
]
```

### Tables SQLite ajoutées

```sql
CREATE TABLE cycle_checkpoints (
    cycle_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    state_json TEXT NOT NULL,
    ok INTEGER NOT NULL,
    completed_at TIMESTAMP NOT NULL,
    PRIMARY KEY (cycle_id, phase)
);

CREATE TABLE global_memory (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    source_project_id TEXT,
    category TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE run_metrics (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    approve_rate REAL,
    duration_ms INTEGER,
    tokens INTEGER,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE cycle_annotations (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL
);
```

### Events à ajouter

- `PhaseCheckpointed(cycle_id, phase)` — hook pour UI
- `CycleBlocked(reason, resume_at)` — G3 rate limit, G4 readiness
- `AnomalyDetected(phase, factor, baseline_ms)` — I3
- `MemoryPromoted(entry_id, from_project, to_scope)` — J1
- `ModelRouted(project, phase, from_model, to_model, reason)` — L3

### Tests nouveaux

- `tests/application/test_checkpoint_repo.py` — persist/load par phase
- `tests/application/test_claude_timeout.py` — backoff + retries
- `tests/infrastructure/test_github_rate_limit.py` — circuit breaker
- `tests/agents/test_qa_subagents.py` — 4 sous-agents chaînés
- `tests/domain/test_agent_state_union.py` — discriminated union valide
- `tests/application/test_anomaly_detector.py` — baseline drift
- `tests/application/test_model_router.py` — up/downgrade logique
- `tests/e2e/test_cycle_resume.py` — Playwright crash → resume
- `tests/e2e/test_gallery.py` — `/gallery` affiche démos publiques

---

## 7. KPIs pour mesurer qu'on a réussi

| KPI | Cible | Mesure |
|-----|-------|--------|
| % de cycles failed qui reprennent avec succès | > 80% | G1+G5 |
| Latence p95 phase vs baseline | < 1.5× | I2+I3 |
| Nombre d'entries mémoire globales utilisées (agents pull-down) | > 10/semaine | J1 |
| % de projets avec `auto_routing=true` | > 50% après 1 mois | L3 |
| Réduction tokens/cycle moyenne | -20% | L2+L3 |
| Temps « cycle started → démo cliquable » | < 5 min | tout le plan |
| 0 cycle bloqué > 15 min sans toast SSE `CycleBlocked` | oui | G3+G4 |
| Démos publiques scrapables OG-preview (Twitter/LinkedIn) | 100% | L4 |

---

## 8. Résumé exécutif (TL;DR)

1. **A→F c'est fait**, et c'est déployé sur `bots.jrec.fr/swarm`. On a le produit démo jouable + controls par projet + replay + mémoire + pluggabilité.
2. **La production nous montre les vraies douleurs** : pas de checkpoint, pas de traces, pas de timeouts adaptatifs, mémoire cloisonnée. Sprint G→L règle ça.
3. **Ordre délibéré** : résilience (G) avant state cleanup (H) avant observabilité (I) avant cross-project (J) avant human-in-loop (K) avant auto-amélioration (L). Ship la plomberie avant la peinture.
4. **Chaque sprint G→L livre sa vidéo `docs/demos/sprint-<X>.webm`** — le dogfooding devient la règle stricte (pas de démo = pas de merge).
5. **Edge unique visé post-L** : TheSwarm est le seul outil agent dev qui **reprend un cycle planté**, **apprend d'un projet à l'autre**, et **mesure sa propre amélioration**. Devin/Factory/Sweep n'ont aucun des trois.
