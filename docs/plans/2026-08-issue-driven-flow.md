# Issue-driven flow — plan produit (2026-08)

Objectif utilisateur, verbatim : « connecter un repo GitHub, ça liste les projets,
on en choisit un, ça liste les GH issues, on choisit une GHI, on clique sur play,
ça lance l'implémentation de la GHI. On peut suivre l'implémentation visuellement
(le PO fait ci, le dev en est là, la feature a été découpée en X features, on peut
lire les démos de chaque feature). »

Pivot : l'unité d'action passe de « cycle sur un repo » (drainage de backlog) à
« implémente CETTE issue ». Le pipeline backend sait déjà presque tout faire —
le breakdown TechLead crée des sous-issues `Parent: #N`, la QA produit des
captures/vidéos par story (`story_screenshots`, `story_videos`), le suivi live
SSE existe. Ce qui manque est le ciblage et la mise en scène.

## État de l'existant vs cible

| Étape du flow cible | Existant | Manque |
|---|---|---|
| Connecter un repo | `/projects/new` OK | — |
| Lister les projets | `/projects/` OK (cartes pauvres) | statut dernier cycle, compteur d'issues ready |
| Lister les GH issues | rien côté UI (`GitHubClient.get_issues` existe) | route + fragment HTMX board d'issues |
| Choisir une issue + Play | `POST /api/cycle {repo}` seulement | param `issue_number`, bouton ▶ par issue |
| Le pipeline traite CETTE issue | `pick_task` prend la 1re `role:dev+status:ready` | honorer `target_issue` (la pinner, la mettre ready si besoin) |
| « découpée en X features » | breakdown crée les sous-issues `Parent: #N` | requête inverse (children d'un parent) + affichage arbre |
| Suivi visuel par agent | timeline de phases + live-progress SSE sur `/cycles/{id}` | en-tête « Issue #N », chips par sous-tâche, liens PR inline |
| Démos par feature | `story_screenshots`/`story_videos` dans le demo_report | les afficher sur la page cycle (aujourd'hui invisibles) |

## Phases

### P1 — Play sur une issue (backend)
- `CycleRequest.issue_number: int | None`; propagé via `CycleConfig.target_issue`.
- `dev.pick_task` : si `target_issue` est défini, prendre cette issue exactement
  (la passer `status:ready→in-progress` quel que soit son état de départ) ;
  breakdown TechLead scopé au parent ciblé ; les itérations suivantes du dev loop
  consomment ses enfants `Parent: #N` en priorité.
- Done : `POST /api/cycle {"repo": …, "issue_number": N}` implémente #N et rien
  d'autre ; test d'intégration sur le ciblage.

### P2 — Board d'issues + Play (UI)
- `GET /projects/{id}/issues` (fragment HTMX) : liste des GH issues ouvertes,
  colonnes par label `status:*`, bouton ▶ sur chaque issue actionnable.
- La page projet mène ce board (le Sprint composer reste au-dessus : décrire →
  le PO rédige des issues → elles apparaissent dans le board → Play).
- Done : depuis `/projects/concert-tour-app`, cliquer ▶ sur une issue ouvre le
  cycle lancé dessus.

### P3 — Suivi visuel du cycle (mise en scène)
- En-tête de `/cycles/{id}` : issue ciblée (titre + lien GitHub), agent actif.
- Arbre de découpage : sous-issues du parent avec chip d'état vivant
  (`ready / in-progress / review / merged`) via SSE.
- PR ouvertes/mergées cliquables dans la timeline ; artefacts par story
  (captures + vidéos, déjà stockés) rendus par sous-tâche.
- Remplacer la page morte `/cycles/{id}/live` (« No preview URL template ») par
  ce suivi ; le preview d'app reste optionnel si le template est configuré.
- Done : pendant un run réel on voit, sans recharger : phase courante, tâche en
  cours, X/Y sous-tâches terminées, liens PR, démos consultables.

### P4 — Vérité des KPI + dashboard recentré
- Corriger `success_rate_7d` / `cost_7d` (0 % et $0.00 affichés sous une table
  qui montre 8 completed — requête fenêtre 7 j cassée).
- Dépriorer le widget « tour » (replié par défaut) ; déplacer Intel
  feed/sources/clusters hors du dashboard ; cartes projets enrichies
  (dernier cycle, issues ready, coût 7 j).
- Done : chiffres du bandeau = ce que la table raconte ; le premier écran montre
  l'activité, pas un carrousel.

### P5 — Finitions collant au flow
- Redirect 307 sans slash (`/demos` → `/demos/`).
- `commit_all` : exclure les artefacts runtime (`test.db*`, coverage) — la PR
  poubelle #192 en venait.
- Fragments lents de la page projet (« Loading… » persistants) : précharger
  côté serveur ou squelettes.

Ordre conseillé : P1 → P2 → P3 (le cœur de l'objectif), P4 en parallèle possible,
P5 au fil de l'eau. Chaque phase se termine par un cycle réel de validation sur
concert-tour-app, mergé et vérifié en prod.
