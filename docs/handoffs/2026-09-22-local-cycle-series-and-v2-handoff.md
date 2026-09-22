# Série de cycles locaux (19–22 septembre 2026) — bilan et passation vers la V2

**Pour** : l'agent / l'équipe qui implémente la V2 (`docs/plans/` — *V2 — le moteur*).
**Écrit par** : l'agent du owner, à la fin de la session, à partir des journaux
(`tmp/local-cycle/*.log`, non versionnés) et de GitHub. Tout ce qui est affirmé ici
a été observé ; ce qui n'est que supposé est marqué comme tel.

**Point de départ de la V2** : `main` à `5717fb86` (2026-09-22). Tout ce que cette
session a produit y est mergé et déployé sur `bots.jrec.fr/swarm`.

---

## 1. Résumé en cinq lignes

1. Sept cycles de la swarm sur son propre dépôt, depuis un portable, en trois jours.
   **Trois sont conformes** au critère durci du owner (`completed` + une PR + aucune
   sous-tâche orpheline) : les cycles 5, 6 et 7. L'objectif initial était dix d'affilée.
2. **Douze correctifs déployés**, chacun trouvé par un cycle réel, chacun avec un test
   écrit avant lui. Ils touchent presque tous la *plomberie* autour des agents, pas les
   agents eux-mêmes.
3. **La boucle de revue est fermée pour la première fois** : un `REQUEST_CHANGES` motivé
   (une injection CWE-78 trouvée par le relecteur dans une PR de la swarm) a été rendu
   au Dev, qui a repris sa branche, corrigé, documenté, et obtenu `APPROVE` — sans
   intervention humaine entre les deux cycles.
4. **La cause la plus coûteuse n'était pas dans le produit** : les hooks `Stop` de
   Claude Code de l'hôte se déclenchaient dans chaque `claude -p` de la swarm et
   remplaçaient le dernier message des relecteurs — le seul que `--output-format json`
   conserve. Ce mécanisme est la clé de lecture de la V2 : **ce qui se joue au niveau
   du sous-processus disparaît avec le SDK, ce qui se joue au niveau du workflow reste.**
5. **Trois choses ne sont pas prouvées** : le merge automatique de fin de cycle (livré,
   jamais exercé), la cause d'un `coverage 0.0%` ponctuel, et le motif des timeouts de
   revue (trois sur sept cycles).

---

## 2. La demande d'origine, et ce qu'elle est devenue

> « état du projet (dernière fonctionnalité, puis-je m'en servir ?) » → « teste un cycle
> en local » → « continue jusqu'à ce que 10 cycles de suite se déroulent correctement,
> envoie le lien de chaque démo ici ».

La dérive est réelle et elle est volontaire : chaque cycle révélait un défaut qui
empêchait le cycle suivant de rien mesurer. Le chemin de « tester un cycle » à « douze
correctifs » est le mécanisme décrit dans la feuille de route #79 (*cycle réel → défaut →
correctif → cycle réel*), pas une dispersion. Mais le compteur reste à **3/10**.

Les démos de chaque cycle ont été envoyées en pièces jointes (captures + GIF) : un cycle
local ne produit pas d'URL, ses artefacts vivent dans `~/.swarm-data/artifacts/AAAAMMJJ/`.

---

## 3. Chronologie

Heures locales (Paris). Coût = `cost_usd` rapporté par le cycle, sur l'abonnement
partagé avec les sessions du owner.

| # | Date, cible | Durée | Coût | PR | Verdict QA | Ce que ce cycle a appris |
|---|---|---|---|---|---|---|
| — | 19/09 08:06, `run-cycle` | 11 s | 0 | — | — | Aucun backend Claude (CLI expiré, API sans crédit). **A poussé un plan quotidien vide sur `main`** → #159 |
| 1 | 19/09 14:59, `run-cycle` | 10 min | ~1,26 | 0 | — | `techlead_breakdown` > 600 s ; a créé #160 #161 #162. **Un timeout masqué par la sonde d'auth** → #163 |
| 2 | 19/09 15:37, #160 | 57 min | 3,88 | #164 | `unit=165(fail) e2e=0 shots=0` | Interpréteur 3.11 vs `>=3.12` ; install ratée lue comme suite rouge ; 2 tours Ralph à vide ; démo morte ; revue morte à 300 s → **A, B, C** |
| 3 | 19/09 16:35, #161 | 25 min | 2,01 | #165 | `unit=2889(fail) e2e=0 shots=2` | PATH forcé sur 3.12 : install OK, première démo. **Relecteurs contaminés par le hook** ; PR ouverte par Claude hors comptabilité → **E, F** |
| 4 | 20/09 07:07, #162 | 36 min | 5,68 | #168 | `unit=2903(fail) e2e=0 shots=2` | A vérifié seul ; phase de revue tient 15 min (C ok) ; verdict `REQUEST_CHANGES` réel **perdu** en `COMMENT` ; démo vivante |
| — | 20/09 | | | | | **Suppression des hooks** `Stop` (utilisateur + projet) |
| 5 | 20/09 18:07, #49 | 40 min | 6,63 | #169 | `unit=2906(fail) e2e=0 shots=2`, cov 87 % | Revues **structurées, propres** ; #168 `REQUEST_CHANGES` → **#162 rendue au Dev** (vérifié sur GitHub) ; 2 `APPROVE` retenues ; `e2e=0` à cause du **port 8000 tenu par un autre processus** → **G** |
| 6 | 21/09 08:17, #162 | 28 min | 5,85 | #172 | `unit=2927(fail) e2e=8(fail) shots=2`, cov **0,0 %** | **`resume_branch` exercé** (première fois) ; garde scopé : 1 fichier, 1 s, `Tests PASSED` ; **le Dev corrige l'injection** + ajoute le `paths-ignore` ; 2 `APPROVE` ; e2e s'exécute enfin (port 8003) |
| 7 | 22/09 11:15, #50 | 31 min | 4,95 | #174 | `unit=2941(fail) e2e=20(fail) shots=2`, cov 87 % | Revue expirée ×2 (261 s) ; rien d'approuvé donc **merge de fin de cycle non exercé** |

Entre les cycles 6 et 7, le harnais planifié introduit par #172 s'est déclenché seul
dans la nuit (`e8e1c73 chore: harness run 2026-09-22`), a écrit sur `main`, et **n'a
pas redéployé** — le `paths-ignore` ajouté par le Dev sur recommandation des relecteurs
a été vérifié par la réalité.

---

## 4. Ce qui a été livré

Tous mergés en squash sur `main`, CI verte, déployés, prod saine après chaque
déploiement. « Vérifié en vrai » = observé dans un cycle réel *après* déploiement.

| SHA | PR | Contenu | Vérifié en vrai |
|---|---|---|---|
| `ee85dbe6` | #159 | Un backlog vide ne pousse plus de plan fantôme sur `main` | ✅ cycle 1 : « skipping the daily plan commit », `main` intact |
| `8ab3458f` | #163 | Une sonde de jeton ratée ne masque plus le timeout derrière elle → la reprise grandit son budget | ✅ cycle 2 : « timed out at 600s — retrying with 780s » |
| `37b02557` | #166 | Une installation ratée est `tests_unavailable` (Dev **et** QA), pas une suite rouge | ⚠️ par tests seulement — la cause locale (interpréteur) a été supprimée juste après |
| `ad31a9d6` | #167 | **F** la branche fait foi, pas l'auteur du commit · **A** `find_system_python` honore `requires-python` · **C** phase de revue 30 min · **E** un `APPROVE` nu récupéré dans la prose devient `COMMENT` | ✅ A (cycle 4+), C (cycle 4+), E (cycle 4), F (cycle 6 : `prs [172]`) |
| `1f738316` | #170 | **G** port de base libre pour les serveurs QA · budget de tests Dev 900 s + `dev_iter` 60 min | ✅ G (cycles 6–7 : « Port 8000 is taken… using 8003 ») · budget remplacé par #171 |
| `8f8bcbf2` | #171 | Le garde Dev ne fait tourner que les tests touchés par le diff ; `dev_iter` 40 min, borné des deux côtés | ✅ cycles 6–7 : « Running 1 test file(s)… Tests PASSED » en 1–4 s |
| `a3511cf7` | #165 | (swarm, cycle 3) détection de régression du harnais e2e | — |
| `22392d86` | #172 | (swarm, cycle 6) harnais planifié + **correctif CWE-78** + `paths-ignore` | ✅ le harnais a tourné seul sans redéployer |
| `71dd5aae` | #169 | (swarm, cycle 5) `RepoAccessGuard` | — |
| `639ae8b5` | #173 | Les PR approuvées se mergent **en fin de cycle** sur SELF_REPO | ❌ **jamais exercé** (cycle 7 n'a rien approuvé) |
| `839342b6` | #175 | 0 % de couverture sous suite verte = `not_run` · attente du test fragile 4 s → 20 s | ⚠️ le cas 0 % ne s'est pas reproduit |
| `5717fb86` | #174 | (swarm, cycle 7) refus précoce si le credential ne lit pas le dépôt — **mergée par l'agent du owner après lecture**, la revue ayant expiré deux fois | — |

Fermées sans merge : #168 (supplantée par #172 après `REQUEST_CHANGES`), #164 (en
conflit avec #165, contenu déjà dans `main`, revue expirée deux fois).

Hors dépôt : deux hooks `Stop` Claude Code supprimés (sauvegarde dans
`~/.claude/hooks-backup-20260920T160308Z/`), un hook `PreToolUse` `headroom` redondant
migré vers `SessionStart`, `~/.claude/CLAUDE.md` vidé par le owner.

---

## 5. Les défauts, un par un

Chaque ligne : ce qu'on a vu, pourquoi, ce qui a été fait, et **à quel niveau il se
joue** — c'est la colonne qui compte pour la V2.

| | Symptôme observé | Cause | Correctif | Niveau |
|---|---|---|---|---|
| PO | Plan quotidien vide commité sur `main` par un cycle mort 30 s plus tard | La branche « rien à planifier » renvoyait sa phrase *comme plan* ; le garde aval ne testait que la vacuité | #159 | workflow |
| CLI | Timeout classé « auth » ; la reprise repart sur le même budget épuisé | La sonde « sans jeton » échoue en 2 s et son erreur d'auth *remplace* le timeout d'origine, que `_retry_timeout` seul sait faire grandir | #163 | **sous-processus** |
| A | `Package 'theswarm' requires a different Python: 3.11.6 not in '>=3.12'` | `find_system_python` prend le premier `python3` du PATH sans lire `requires-python` | #167 | workflow |
| B | 165 erreurs d'import lues comme suite rouge, 2 tours Ralph, PR « Some tests failing » | `install_target` journalisait l'échec et le jetait ; pytest *était* là, le paquet cible non | #166 | workflow |
| C | `Phase techlead_review exceeded 300s` avec un appel doté de 780 s | Budget d'appel > budget de phase ; #130 avait réduit le *nombre* de revues sans réconcilier les deux | #167 | workflow |
| E | Relecteur qui répond *« I'm not going to run through that wrap-up checklist »* ; verdict perdu ; un `APPROVE` égaré pris pour une approbation | Le hook `Stop` de l'hôte se déclenche dans `claude -p` et déplace le **dernier message**, le seul conservé par `--output-format json` — même mécanisme que #125 | hooks supprimés ; garde produit #167 | **sous-processus** + environnement |
| F | `prs []` alors que la PR existe ; note d'échec mensongère sur l'issue | Claude (acceptEdits + Bash) committe et pousse lui-même ; `commit_all` répond « rien à committer » | #167 | workflow |
| G | `server … not ready after 90.0s (status=400) — server still running but not serving`, `e2e=0(pass)` ×4 | `E2E_PORT = 8000` codé en dur ; un `solana-te` tenait le port sur le portable | #170 | workflow |
| Budget Dev | `tests_unavailable` à chaque itération sur ce dépôt (120 s pour 3 min de suite) ; à 900 s, une itération = 1 h | Le garde faisait tourner *toute* la suite | #171 (scopé au diff) | workflow |
| Merge | `held_prs` s'accumulent, chaque PR approuvée attend une main | Retenue permanente sur SELF_REPO | #173 (fin de cycle) | workflow |
| Couverture | `coverage 0.0%` filé en `fail` à côté de 2 921 tests verts | `coverage.json` présent avec `num_statements = 0` — jauge débranchée, pas mesure basse | #175 | workflow |
| Flake CI | Test de #149 rouge sur runner chargé (8 min 51 au lieu de 2 min 54), vert à la relance | Attente de 4 s pour une tâche de fond | #175 (20 s) | tests |

**Deux lignes seulement sont du niveau « sous-processus »**, et elles ont coûté le plus
cher en diagnostic. C'est l'argument empirique pour la décision 1 de la V2.

---

## 6. Ce qui est vérifié en conditions réelles

Observé dans les journaux d'un cycle réel, après déploiement, pas seulement par un test.

- **La boucle `REQUEST_CHANGES` → Dev → `APPROVE`** (#121/#157) : revue recopiée sur
  l'issue derrière `<!-- swarm:changes-requested -->`, label repassé `status:ready`,
  branche reprise (`git.resume_branch`, #123 — première exécution réelle), correctif
  appliqué avec le commentaire explicatif, approbation au cycle suivant.
- **Un relecteur automatique a trouvé une vraie faille** (CWE-78 dans un workflow
  détenant un token push-to-main) et **la swarm l'a corrigée elle-même**.
- **Le garde de tests scopé** mesure enfin quelque chose sur un dépôt de 2 900 tests :
  1 fichier, 1 à 4 s, verdict réel, corps de PR « All tests pass » véridique.
- **Le choix d'interpréteur, le port libre, le `paths-ignore`** — chacun a produit sa
  ligne de log attendue dans un cycle et le comportement aval a changé (install OK,
  e2e exécutés, harnais sans redéploiement).
- **Les garde-fous de fin de cycle** (#107, #131) : sept cycles, ~20 commits de fin de
  cycle sur `main`, zéro déploiement déclenché.
- **Un appel Claude qui échoue saute l'étape** (#150) : trois revues expirées, aucun
  cycle tué.

---

## 7. Ce qui est fragile ou non prouvé

À prendre tel quel, pas à « corriger avant la V2 » — sauf mention contraire.

| Sujet | État | Pour la V2 |
|---|---|---|
| **Merge de fin de cycle** (#173) | Déployé, 4 tests unitaires, **jamais exercé** | Le prochain cycle qui approuve quelque chose le prouvera ou non. Si la V2 reprend l'orchestration dans LangGraph, ce nœud est à réimplémenter, pas à porter |
| **Timeouts de revue** | 3 sur 7 cycles (#164 ×2, #174), toujours ~260–290 s ; les cycles 5–6 tenaient en ~3 min | `_review_timeout = 60 + 15 s/1000 car.` sous-estime peut-être pour ce dépôt. Avec le SDK et le streaming, le timeout brut devient un signal d'inactivité — le problème change de nature |
| **`coverage 0.0%`** au cycle 6 | Une occurrence ; 87 % aux cycles 5 et 7 ; `coverage.json` présent | Cause inconnue. Hypothèse non vérifiée : `pip install -e .` réécrit le `.pth` (constaté **en double** dans `_editable_impl_theswarm.pth` après deux cycles) et une fenêtre existe. #175 rend la prochaine occurrence honnête |
| **6 échecs unitaires QA** constants (cycles 3–7) | Non identifiés — la sortie est tronquée dans le rapport | Localement hors bac à sable : 3 échecs (`FileNotFoundError: 'python'`, pas de binaire `python` nu). Les 3 autres sont propres à l'espace QA. À nommer une fois |
| **e2e sur soi-même** | 8 puis 20 tests *exécutés*, tous en échec | Jamais vert dans cette série (AGENTS.md rapporte un 20/20 vert sur `28536a4f58b9`, en prod). Non investigué |
| **Import transitoire** (cycle 5) | `ModuleNotFoundError` sur un fichier bien placé, résolu à la reprise | Une occurrence ; même hypothèse `.pth` que la couverture |
| **`semgrep`** | Absent de l'image, porte sécurité `not_run` à chaque cycle | Décision de dépendance (~100 Mo) qui appartient au owner depuis le 18/09 |
| Compteur | **3/10** | Le critère durci ne demande pas de revue ; le cycle 7 passe avec une PR non relue |

---

## 8. Faits sur l'environnement local (le portable du owner)

Ils ont coûté des cycles ; ils sont vrais au 22/09.

- **PATH** : `python3` → 3.11.6 en tête, puis 3.12.0, 3.14.6 ; aucun binaire `python` nu
  (d'où 3 tests `test_tools_claude_run.py` qui échouent localement, jamais en CI).
- **Port 8000** tenu par un processus `solana-te` (PID 17357 le 20/09) qui répond 400.
- **Credentials** : le CLI utilise `CLAUDE_CODE_OAUTH_TOKEN` dans `.env` (frappé par
  `claude setup-token`, valide un an). L'ancienne `ANTHROPIC_API_KEY` (`sk-ant-api`,
  solde zéro) a été écrasée lors du collage du jeton — perdue, sans impact pratique.
- **Hooks Claude Code** : plus aucun `Stop` à aucun niveau ; un seul `SessionStart`
  (`headroom`). Sauvegarde complète dans `~/.claude/hooks-backup-20260920T160308Z/`.
- **Bac à sable de l'agent** : `gh` et `urllib` échouent la vérification TLS du proxy ;
  `curl` avec `$(gh auth token)` fonctionne. Les tests qui ouvrent des sockets
  (`test_readiness`, `test_e2e_port_is_free`) ne passent qu'hors bac à sable.
  `git checkout -B … origin/main` échoue silencieusement (écriture de `.git/config`
  refusée) → `--no-track` et vérifier `git branch --show-current`.
- **Abonnement partagé** : les cycles et les sessions du owner tirent sur la même
  fenêtre Max. Un cycle sur soi-même : 2 à 7 $, 25 à 57 min.

---

## 9. Procédure de run local

```bash
bash scripts/local_cycle/run-targeted.sh <issue>   # cycle ciblé, forme du bouton Play
```

Journaux : `tmp/local-cycle/targeted-<issue>-<horodatage>.log`. Artefacts de démo :
`~/.swarm-data/artifacts/AAAAMMJJ/{screenshot,video}/`. Ne pas utiliser
`python -m theswarm run-cycle` sur ce dépôt (cycle quotidien : découpage de tout le
backlog, ~220 s par issue dans une phase de 600 s). Détail dans
`scripts/local_cycle/README.md`.

---

## 10. Lecture pour la V2 — décision par décision

Le document V2 m'est parvenu tronqué (section 0 complète, section 1 jusqu'à « reprend à
la granularité de la »). Ce qui suit s'appuie sur ce que j'ai lu.

### Décision 1 — le Claude Agent SDK remplace `claude -p`

C'est la décision que cette série justifie le mieux. Ce qui **devient caduc** avec elle :

- Toute la classe « dernier message » : #125 (les blocs `--- FILE:` perdus dans un message
  intermédiaire) et **E** (le hook qui déplace le verdict). Avec un flux de messages, le
  verdict n'est plus « ce que Claude a dit en dernier ».
- **#163** et, plus largement, `_cli_with_auth_recovery`, `_retry_timeout`, les planchers
  de timeout persistés (#133/#153), la détection de quota par texte, le repli API,
  `_envelope_error` : ~700 lignes de `tools/claude.py` qui existent parce qu'un
  sous-processus est une boîte noire jusqu'à sa sortie.
- **Le salvage de verdict dans la prose** (#107, #120, #130, et le garde E de #167) : avec
  une sortie structurée ou un appel d'outil, `decision` est un champ, pas une regex.

Ce qu'il faut **vérifier** avant de le considérer réglé : le SDK exécute Claude Code
sous le capot. **Charge-t-il `~/.claude/settings.json`, les hooks et les `CLAUDE.md` de
l'hôte ?** Si oui, la contamination E survit au changement de transport. La série n'a
pas pu le tester ; c'est la première chose à mesurer au jalon qui remplace l'appel de
revue.

Ce qui **se transporte tel quel**, parce qu'il ne dépend pas de la façon d'appeler
Claude : A (interpréteur), B (install ratée), F (la branche fait foi), G (port),
le garde scopé (#171), le PO (#159), les bornes de phase (C — mais voir décision 2).

### Décision 2 — LangGraph avec checkpointer SQLite

- **Le tracker en mémoire (#5)** est la cause racine de la règle « ne jamais déployer
  pendant un cycle », de la retenue des merges sur SELF_REPO, et donc de #173. Un cycle
  durable qui reprend au nœud près après un redéploiement rend #173 **inutile** : le
  TechLead peut merger dans sa phase, le redéploiement reprend le cycle là où il était.
  *À condition* que la reprise soit prouvée en prod avec un vrai redéploiement au milieu
  d'une revue — c'est le test d'acceptation à écrire en premier.
- **Les budgets de phase** (`PHASE_TIMEOUTS`, C, `dev_iter` borné des deux côtés) sont
  aujourd'hui des `asyncio.wait_for` impératifs dans `cycle.py`. Si l'orchestration passe
  dans le graphe, ils deviennent des propriétés de nœuds. Les deux tests d'invariant
  (`test_review_budget_fits_its_phase.py`, `test_dev_iteration_budget.py` +
  `test_persisted_timeout_floor.py`) disent *ce qui doit tenir* ; ils sont à réécrire
  contre la nouvelle forme, pas à supprimer.
- **`_announce` / `PHASE_OWNER`** (les phases sont annoncées, pas devinées) : le théâtre
  en dépend. Un graphe qui streame ses transitions le remplace naturellement.

### Décision 3 — aucun nouveau service

Rien dans cette série n'en a demandé. `semgrep` reste la seule dépendance en suspens, et
c'est une dépendance d'image, pas un service.

### Décision 4 — chaque jalon vérifié en prod par un vrai cycle

C'est exactement la méthode de cette série, et elle a un coût que le tableau §3 chiffre :
**~30 min et ~5 $ par cycle, sur l'abonnement partagé**. Deux conséquences pratiques :

- Les cycles *locaux* ont trouvé des défauts que la prod ne montrait pas (A, G, E — tous
  liés à l'environnement du portable). Ils ne remplacent pas la vérification en prod ;
  ils la précèdent utilement.
- Un jalon vérifié par un cycle réel exige un backlog `status:ready` + `role:dev` à
  consommer. Au 22/09 il reste #54, #55, #56 dans la famille RepoAccessGuard.

### Décision 5 — la V1 reste

Tout ce que cette session a écrit est dans `src/theswarm/{agents,tools,cycle.py}` — la V1
au sens du document. À la V2 de décider ce qui est *réécrit* et ce qui est *enveloppé*.
Le §5 (colonne « niveau ») est la carte : le workflow se transporte, le sous-processus
disparaît.

---

## 11. Ce qu'il ne faut pas transporter

- `python -m theswarm run-cycle` comme entrée pour un cycle sur ce dépôt.
- Un port codé en dur, une durée de test codée en dur pour « toute la suite ».
- Le parsing de verdict dans la prose, une fois qu'un verdict est un champ.
- `_timeout_floor` / `cli_timeout_floors` : c'est de l'apprentissage autour d'un
  sous-processus opaque.
- La retenue permanente des merges (#173 l'a déjà remplacée ; la durabilité la rendra
  inutile).
- Tout hook `Stop` sur la machine qui lance des agents.

---

## 12. Issues et PR touchées

**Issues** : #49 (livrée, #169), #50 (livrée, #174), #160 (PR #164 fermée supplantée —
le fond est dans #165), #161 (livrée, #165), #162 (livrée, #172 après un aller-retour de
revue), #79 (feuille de route — à mettre à jour avec ce document). Ouvertes pour la
swarm : #54, #55, #56 ; #147 (persister la raison d'échec).

**PR de l'agent du owner** : #159, #163, #166, #167, #170, #171, #173, #175.
**PR de la swarm** : #164 (fermée), #165, #168 (fermée), #169, #172, #174.

---

## 13. Ce qui manque à ce rapport

- Le document V2 au-delà de la section 1, et sa section 8 (décisions bloquantes).
- L'analyse des 6 échecs QA constants et des e2e rouges sur soi-même.
- Une mesure en prod des correctifs A, B, G, #171, #173 : tous ont été vérifiés par des
  cycles *locaux*. La prod a le même code, pas la même machine.
