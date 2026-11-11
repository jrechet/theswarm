# Plan — la V2 qui tient, puis les équipes (2026-11-11)

Demande du propriétaire, 2026-11-11 : nettoyer le dépôt, s'assurer que la V2
fonctionne (plusieurs projets à la fois, savoir où en est chaque agent, pouvoir
lui parler), puis faire de TheSwarm un **harness modulable** : des personas
créés graphiquement, une équipe par projet, des enchaînements dessinés, le tout
adossé à un fichier YAML, et un MCP devant pour que des agents pilotent le
logiciel.

Vocabulaire : « V2 » désigne ici le produit tel qu'il tourne (le moteur de
`2026-09-v2-runtime.md` sous l'interface de `2026-10-v3-one-product.md`, tous
deux livrés). Ce que le propriétaire appelle « V3 » — équipes, personas, MCP —
est la **phase B** de ce plan. Elle revient sur une décision écrite du plan
d'octobre (« deux idées repliées dans les rôles existants, pas des personas »).

## 1. État des lieux (mesuré le 2026-11-11)

**Dépôt.** 228 branches distantes et 219 locales supprimées ; toutes avaient une
PR (217 fusionnées en squash, 9 fermées exprès, 1 ouverte). PR #321 fermée
(conflit, migration `v037` déjà prise, besoin disparu) avec #317–#319. Il reste
`main`. La forge Forgejo ne reçoit rien : le secret `FORGE_TOKEN` n'a jamais été
posé, le miroir « réussit » sans rien pousser (une seule branche y vit,
`feat/forge-hybride`).

**Prod.** Elle tourne le dernier code de `main` (3dfbc3b, 17 octobre). Les 30
derniers cycles sont le harness quotidien sur concert-tour-app : 30 sur 30
verts, 27 min et 3,09 $ en médiane. **Rien d'autre n'a tourné depuis le 11
octobre** : ni deux cycles à la fois, ni un autre dépôt. Le parallèle livré le
17 octobre (#330) n'avait jamais été exercé en prod.

**Ce que le premier essai parallèle a montré** (`scripts/parallel_e2e.py`, trois
features lancées ensemble) : deux cycles ont tourné côte à côte sur le même
dépôt, chacun dans son clone, découpage puis Dev, sans se gêner pendant huit
minutes — puis **la fenêtre d'abonnement Claude s'est fermée** et les trois ont
échoué. La fenêtre est partagée entre la prod et le Claude Code du
propriétaire : cette session de travail l'a vidée. Un cycle qui rencontre le
mur meurt ; il devrait attendre.

**Défauts trouvés** (✔ = corrigé dans cette branche) :

| # | Défaut | Preuve |
|---|---|---|
| 1 ✔ | DevOps dit « le déploiement n'a pas abouti » depuis 25 jours et propose de redéployer une image que rien n'a construite | le run de déploiement sort de la fenêtre des 30 derniers runs (`devops.py`, `RUN_LIMIT`) |
| 2 ✔ | Une proposition DevOps reste ouverte pour toujours (« redémarrer le runner » depuis le 15 octobre, runner revenu) — un clic l'exécute | `proposals.raise_from` ne retirait rien |
| 3 ✔ | L'accueil dit « issue #841 · running since 08:43 » : ni titre, ni étape, ni agent, ni signe de vie, pas de rafraîchissement | `home._now_cards` |
| 4 | La page projet ne nomme qu'un des cycles en cours et range les features en cours dans « Backlog », « Building 0 » | `project.py:272-290`, `common._board_status` |
| 5 | Le bouton « Resume » d'un cycle échoué ne peut pas marcher | `theater.py:346` ne passe pas `resume_cycle_id` → `CycleNotResumable` ; le test mocke `run_api_cycle` |
| 6 | L'API ne renvoie jamais la feature d'un cycle (`issue_number: null`) alors que la table la stocke | `CycleDTO` sans le champ, trois requêtes à compléter |
| 7 | Un mur de quota tue le cycle au lieu de le suspendre | `ClaudeFatalError` → `failed` |
| 8 | Le watchdog ne fait qu'écrire dans les logs | construit sans callback (`cycle.py:353`) |
| 9 | Deux Dev en parallèle partagent une seule station « Dev » : on ne sait pas qui fait quelle tâche | un seul `current_role`, pas d'identifiant de tâche sur les événements |
| 10 | Les prompts du Dev et du relecteur n'ont pas le paragraphe anti-injection | `DEV_SYSTEM`, `REVIEW_SYSTEM` : constantes mortes |
| 11 | Le manifeste d'évaluation est épuisé : le harness ne mesure plus rien de neuf | 45 features, toutes livrées |
| 12 | `/api/live/state` est un singleton : deux cycles s'y écrasent | `dashboard.py:18-93` |
| 13 | 69 des 120 services construits au démarrage ne sont lus nulle part (restes de la V1) | `app.py` |

**Deux cycles à la fois : ce que l'audit du code dit** (lecture, pas encore
reproduit). Sur deux dépôts différents, la porte, les clones, les ports et le
théâtre sont sains ; les risques sont la mémoire (deux QA = quatre serveurs de
démo et quatre Chromium dans 4 Go), la fenêtre d'abonnement, et un cycle sur
TheSwarm lui-même dont la fusion finale redéploie sous l'autre. Sur **un même
dépôt** (limite à 2), seuls le découpage et le choix de tâche du Dev sont
propres à la feature :

| # | Risque | Où |
|---|---|---|
| C1 | La revue et la fusion parcourent **toutes** les PR ouvertes du dépôt : le cycle B peut relire, renvoyer ou fusionner la PR du cycle A ; deux renvois comptent deux tours et la tâche est abandonnée ; la démo de B raconte la feature de A | `techlead.py:295`, `:913-953` |
| C2 | « Jamais deux cycles sur une feature » ne compare que l'issue épinglée : Play sur une story puis sur une de ses sous-tâches donne deux Dev sur la même branche | `cycle_gate.py:108`, `dev.py:380-409` |
| C3 | Une PR approuvée dans le cycle fusionne sans être remise à jour sur `main`, que l'autre cycle vient de bouger | `techlead.py:935-953` |
| C4 | Plan et rapport du PO, mémoire, journal : écritures sur `main` non protégées, la dernière gagne | `po.py:199-269`, `memory_store.py:204` |
| C5 | Aucune borne commune sur les captures QA ; un serveur de démo orphelin si la phase est annulée | `qa.py:913-947`, `:1928` |
| C6 | Le PO du matin passe en « ready » jusqu'à trois stories du backlog même dans un cycle ciblé | `po.py:93-143` |

Conséquence : **la limite reste à 1 par dépôt** tant que C1–C3 ne sont pas
corrigés. C'est aussi une partie du ressenti « ça ne marche pas » : à 1, la
deuxième feature d'un projet attend, et l'interface le disait mal.

## 2. Phase A — la V2 qui tient

Règle : chaque jalon se termine par `scripts/parallel_e2e.py` vert en prod, pas
par des tests unitaires seuls.

**A0 — finir ce qui est en cours (1 jour).** Défauts 4, 5, 6, 11 ; suite
complète ; déploiement ; l'essai parallèle rejoué jusqu'au vert. Le harness
quotidien gagne une variante hebdomadaire « trois à la fois ».

**A1 — un cycle ne meurt plus pour une raison qui passe (3 jours).**
- Statut `waiting` avec sa raison : mur de quota (reprise à l'heure que le
  message donne), CI en cours, file d'attente. Un mur suspend le cycle à la
  frontière du nœud — le graphe est déjà durable — et le relance tout seul.
- Le watchdog publie un événement `AgentStalled` ; le théâtre et l'accueil le
  montrent ; passé un seuil, l'appel est interrompu et repris (c'est le chemin
  du timeout, déjà éprouvé).
- Les étapes muettes parlent : installation, tests, push, attente de CI,
  capture de la démo émettent une ligne typée (`step`), avec début et fin.
- Part de la fenêtre : un réglage « ne pas dépasser X % de la fenêtre » lu sur
  `RateLimitEvent.utilization`, que le SDK fournit et que le code jette.

**A1 bis — deux features sur un même projet (4 jours).** C1 : la revue, la
fusion, QA et le rapport d'un cycle ciblé ne voient que les PR des sous-tâches
de sa feature ; la veille de fusion garde le reste. C2 : la porte compare la
feature *et ses sous-tâches*. C3 : toute PR approuvée est remise à jour sur
`main` avant de fusionner. C4, C6 : un cycle ciblé n'écrit ni plan ni rapport
daté sur `main` et ne touche pas au backlog. C5 : une borne commune sur les
captures, un `finally` sur le serveur de démo. Preuve : l'essai parallèle à 2
sur concert-tour-app, vert trois fois, avant de proposer 2 par défaut.

**A2 — la salle de contrôle (3 jours).** L'accueil devient la vue de tous les
projets : par cycle, la feature, l'étape, l'agent, la tâche en cours, le dernier
geste, le temps de silence, la dépense à l'instant (défaut 3 fait ; reste la
dépense en cours, l'attribution par tâche du défaut 9, et l'état persistant —
l'historique des phases vit en mémoire et se perd à un redéploiement).

**A3 — parler à un cycle (5 jours).** Trois marches, chacune livrable :
1. *Boîte de réception.* Table `cycle_inbox`, `POST /cycles/{id}/messages`, un
   champ dans le théâtre ; le message apparaît dans le fil. Livré à l'agent au
   prochain appel d'outil par le hook `PreToolUse` qui existe déjà
   (`additionalContext`) — aucun changement de transport — et en tête du
   prompt au nœud suivant.
2. *Pause et reprise* aux frontières de nœud : `paused` est une annulation
   demandée qui garde l'espace de travail et libère la place ; la reprise est
   le chemin du redémarrage (`resume_cycle_id`), qui répare aussi le défaut 5.
3. *« Arrête, fais plutôt ceci »* : passer de `query()` à `ClaudeSDKClient`
   (`interrupt()` puis `query()` dans la même session). Le message est aussi
   posé sur l'issue derrière `CHANGES_MARKER` pour que le relecteur le lise.
Les horloges (appel, phase, cycle) ne comptent pas le temps de pause.

**A4 — ménage (2 jours).** Retirer les 69 services morts et leurs tables,
unifier les quatre vocabulaires de rôles en un seul, défaut 10, défaut 12.
C'est le préalable de la phase B : on ne rend pas configurable ce qui existe
en quatre exemplaires.

## 3. Phase B — les équipes

### Ce que le code permet, et ce qu'il interdit

Le graphe du cycle a onze nœuds fixes. Quatre ont la même forme (entrer,
appeler un agent, compter, écrire le point de reprise) et se prêtent à une
fabrique. Mais les agents ne sont pas des prompts : le Dev, c'est 1 200 lignes
autour de deux appels à Claude ; le TechLead 1 400 autour de deux ; QA 3 100
autour de quatre. Et **les passages de relais ne sont pas des arêtes de
graphe : ce sont des états GitHub** — labels `status:*`, `Parent: #N`,
commentaires marqueurs, statut de commit `theswarm/review`. « A appelle B » dans
un YAML n'exprime pas ce protocole.

### Mes objections, et ce que je propose à la place

1. **Un éditeur de graphe libre serait une régression.** Ce qui fait la valeur
   mesurée du produit — une PR ne fusionne que sur CI verte, l'arbre de travail
   fait foi, une revue par tête de PR — vit dans le code des rôles. Un graphe
   où l'on peut retirer la revue ou QA produit des équipes qui ne livrent plus.
   → **Des gabarits de flux, pas une toile blanche.** Trois au départ :
   *Feature* (l'actuel), *Correctif* (pas de découpage : Dev → Revue → QA
   ciblée), *Revue seule*. Dans un gabarit, des **emplacements** que
   l'utilisateur remplit, déplace ou désactive quand le gabarit le permet, et
   des **points d'insertion** où il ajoute ses personas (relecteur sécurité
   avant la fusion, rédacteur de documentation après QA, designer avant le Dev).
   L'éditeur est graphique — on voit le flux, on glisse un persona sur un
   point — mais il ne peut pas produire un flux invalide.
2. **Deux sortes de personas.** *Rôles moteurs* (PO, TechLead, Dev, QA) : le
   code reste, l'utilisateur règle le nom, la description, les consignes, le
   modèle, l'effort, les outils (en restriction seulement). *Personas libres* :
   un prompt, un profil (lecture / écriture / texte), un schéma de sortie parmi
   ceux proposés (verdict, liste de constats, fichiers), un effet (commenter
   la PR, bloquer la fusion, ouvrir une tâche). C'est ce que l'utilisateur crée
   de zéro.
3. **La description n'est pas décorative.** Elle entre dans le prompt par
   `base.load_context`, par où passent déjà tous les agents — et devient un
   vrai prompt système, que le code ne règle jamais aujourd'hui.
4. **Le fichier d'équipe ne vit pas dans le dépôt cible par défaut.** Qui peut
   pousser sur la cible écrirait des consignes exécutées avec les identifiants
   du swarm. → La vérité est en base, par projet, éditée par le propriétaire ;
   **export et import YAML** à l'identique (`team.yaml`, validé comme
   `evals.load_manifest`) ; lecture depuis le dépôt seulement si le
   propriétaire l'active projet par projet. Les permissions d'un persona ne
   peuvent que restreindre la politique globale (`decide_tool_use`).
5. **Une équipe est versionnée.** Un cycle épingle la version avec laquelle il
   a démarré ; sans cela une reprise après déploiement rejouerait un autre
   graphe sur un ancien état.
6. **Cela existe déjà en partie, et il faut s'en servir.** CrewAI décrit
   agents et tâches en YAML ; AutoGen Studio et LangGraph Studio dessinent des
   équipes ; Claude Code a ses sous-agents en Markdown ; BMAD distribue des
   personas PM/Architecte/Dev/QA. Aucun ne livre ce que TheSwarm a déjà : le
   cycle durable sur un vrai dépôt, la porte CI, la démo filmée, la mesure
   quotidienne. Donc : **ne pas réécrire un moteur d'agents générique**, rendre
   paramétrable celui qui marche ; et **importer** un sous-agent Claude Code
   (`.claude/agents/*.md` : description, prompt, outils, modèle) comme persona
   libre — le format est le même que `AgentDefinition` du SDK déjà installé.
7. **L'équipe se juge.** Toute équipe passe le harness : un changement d'équipe
   se compare à l'équipe par défaut sur les mêmes features (coût, durée,
   comportement vérifié). Sans cela « modulable » veut dire « non mesuré ».

### Jalons

- **B1 — le persona est une donnée (4 jours).** Un enregistrement par projet :
  identifiant, nom, description, consignes, modèle, effort, profil, outils,
  budgets. Il remplace `agent_settings`, `role_assignments` et les tables
  mortes de prompts. `Réglages → Agents` devient l'éditeur de personas ; les
  quatre rôles moteurs sont les personas par défaut, consignes éditables.
  Le théâtre dessine les stations depuis l'équipe (le gabarit HTML itère déjà).
- **B2 — l'équipe par projet et son YAML (3 jours).** Équipe par défaut de
  l'instance, équipe d'un projet, export, import, versions, épinglage par cycle.
- **B3 — gabarits et points d'insertion (6 jours).** Fabrique de nœuds, nœud
  générique « persona libre », les trois gabarits, le choix du gabarit au
  Play (feature ou correctif).
- **B4 — l'éditeur graphique (5 jours).** Le flux dessiné, glisser-déposer des
  personas sur les emplacements, validation en direct, aperçu du YAML.
- **B5 — le MCP (4 jours).** Serveur MCP HTTP monté dans l'application,
  derrière le mur (clé d'accès en Bearer), outils : lister projets et équipes,
  lire et proposer une équipe, valider un YAML, créer un persona, lancer une
  feature, lire l'état d'un cycle, lui écrire, le mettre en pause. Les
  écritures d'équipe venant d'un agent sont des **propositions** que le
  propriétaire accepte — le modèle des propositions DevOps. « Crée une équipe
  pour ce projet » : un outil qui lit le dépôt (langage, tests, CI) et propose
  une équipe à partir des gabarits.
- **B6 — la mesure (2 jours).** Comparaison d'équipes dans le harness.

Ordre conseillé : A0 → A1 → A3.1 → A2 → A3.2 → A4 → B1 → B2 → B5 (lecture et
pilotage) → B3 → B4 → B5 (équipes) → B6. Le MCP de pilotage vient tôt : il sert
aussi d'outil de test.

## 4. Décisions à prendre par le propriétaire

1. Gabarits avec points d'insertion (proposé) ou toile libre ?
2. La vérité de l'équipe : en base avec export YAML (proposé) ou dans le dépôt ?
3. La fenêtre d'abonnement : la prod garde une part réservée, ou passe sur une
   clé d'API pour ne plus dépendre de l'usage personnel ?
4. La forge : poser `FORGE_TOKEN` ou retirer le montage hybride.
