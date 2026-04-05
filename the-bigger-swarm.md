# The Bigger Swarm

## Vision

**Feature request le matin → demo visuelle le soir. Zero clic.**

TheSwarm est une equipe de dev IA autonome. Tu decris ce que tu veux, elle le construit, le teste, et te montre le resultat en video. Tu approuves ou tu commentes. Elle itere.

Pas de login. Pas de dashboard. Pas de CI vert a interpreter. Tu regardes la demo, tu dis oui ou non.

## Le workflow cible

```
Matin                          Journee                         Soir
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────────────┐
│ Humain decrit    │     │ TheSwarm travaille    │     │ Humain recoit rapport   │
│ ce qu'il veut    │────▶│ plan → code → review  │────▶│ visuel avec demos       │
│ (DM, Jira, etc.) │     │ → test → demo capture │     │ video/screenshot par    │
│                  │     │                       │     │ feature                 │
└─────────────────┘     └──────────────────────┘     └──────────┬──────────────┘
                                                                │
                                                     ┌──────────▼──────────────┐
                                                     │ Humain commente         │
                                                     │ "bouton bleu" ──────────┼──▶ PR feedback
                                                     │ "approuve" ─────────────┼──▶ merge
                                                     └─────────────────────────┘
```

## Ce qui existe (v1.0)

- [x] PO recoit une demande en langage naturel (Mattermost DM)
- [x] PO genere des user stories, humain approuve via boutons
- [x] Dev implemente avec Claude Code dans un workspace isole
- [x] TechLead review le code et les PRs
- [x] QA lance les tests unitaires + e2e + semgrep
- [x] Rapport texte en fin de cycle
- [x] Support multi-repo (allowlist + selection par message)
- [x] Memoire basique (AGENT_MEMORY.md dans le repo cible)
- [x] Admin dashboard (bots.jrec.fr/admin)
- [x] Deploy independant (Docker Swarm + Traefik)

## Ce qui manque

### Milestone 1 : Demo visuelle

**Le game-changer.** Un CI vert ne suffit pas. Il faut voir le produit.

Apres chaque feature implementee, le QA agent :
- Lance l'app localement (docker compose up, npm run dev, etc.)
- Navigue les pages impactees avec Playwright
- Prend des screenshots avant/apres
- Enregistre une video de 30 secondes de la feature en action
- Genere un GIF anime du before/after
- Attache tout au rapport de cycle

**Techniquement :**
- Playwright est deja dans l'ecosysteme (e2e-runner agent existant)
- Le QA agent a besoin d'un navigateur headless dans le container
- Les artefacts (screenshots, videos) sont stockes en local ou sur un bucket S3
- Le rapport HTML les reference directement

### Milestone 2 : Rapport zero-click

L'humain ne devrait pas chercher l'information. L'information vient a lui.

- Un message Mattermost en fin de journee avec un lien vers un rapport HTML
- Le rapport montre chaque ticket traite avec :
  - Status (implemente / en review / bloque)
  - Lien vers la PR
  - Demo visuelle (screenshot cliquable, video playable)
  - Diff resume
- Chaque feature a un bouton "Approve" et un champ "Comment"
- "Approve" → merge la PR automatiquement
- Un commentaire ("le bouton devrait etre bleu") → cree un review comment sur la PR GitHub
- TheSwarm voit le commentaire et itere au prochain cycle

**L'experience :**
```
Tu recois un DM :
"🏁 Rapport du jour — 3 features traitees"
[Voir le rapport] ← un seul lien

Tu ouvres, tu vois 3 cartes. Chacune a une video de 30s.
Tu cliques play. Tu vois la feature.
Tu dis "ok" sur 2, tu commentes "couleur du header trop sombre" sur la 3e.
Tu fermes. C'est fini. 2 minutes.
```

### Milestone 3 : Memoire vivante

Aujourd'hui la memoire est un fichier markdown qu'on append. C'est passif et ca se degrade.

La memoire doit etre **vivante** :
- Avant chaque action, l'agent relit la section pertinente de la memoire
- Apres chaque cycle, les agents **raffinent** la memoire (pas juste append) :
  - Qu'est-ce qu'on a appris ?
  - Qu'est-ce qui a change ?
  - Qu'est-ce qui etait faux et doit etre corrige ?
- Les conventions de code, les erreurs connues, les decisions d'archi — tout est mis a jour
- La memoire est **partagee** entre tous les agents d'un meme projet
- La memoire est **questionnee** : "est-ce que cette approche a deja echoue ?"

**Techniquement :**
- Memoire structuree (pas du markdown libre) : sections typees avec timestamps
- Phase de "retrospective" en fin de cycle : chaque agent contribue ses learnings
- Phase de "compaction" : un agent dedie resumer et nettoie les entrees obsoletes
- Stockage : fichier dans le repo (versionne avec le code) ou base vectorielle pour le search

### Milestone 4 : API headless

Aujourd'hui c'est Mattermost-only. TheSwarm doit etre declenchable par n'importe quoi.

```
POST /api/cycle
{
  "repo": "owner/repo",
  "description": "Add Google OAuth login",
  "callback_url": "https://my-app.com/webhook"
}
```

- CLI : `theswarm cycle --repo owner/repo --description "Add feature X"`
- API REST : n'importe quel outil peut lancer un cycle
- Mattermost : DM comme aujourd'hui
- Slack, Discord : adaptateurs simples
- GitHub : un commentaire `/swarm implement this` sur une issue lance un cycle

### Milestone 5 : Sources de tickets pluggables

Aujourd'hui les demandes viennent par DM. Demain :

- **GitHub Issues** : labels `swarm:todo` → TheSwarm les prend en charge
- **Jira** : webhook quand un ticket passe en "To Do" → cycle lance
- **Trello** : carte deplacee dans une liste "Swarm" → cycle lance
- **Linear** : idem
- Un `TicketSource` protocol avec des adaptateurs par plateforme

### Milestone 6 : Auto-apprentissage

Les agents ne devraient jamais refaire une erreur deja rencontree.

- Quand un humain rejette une PR ou commente un probleme, TheSwarm :
  - Identifie la cause (mauvaise convention ? erreur d'archi ? bug de style ?)
  - Met a jour ses propres instructions/prompts
  - Verifie que le meme pattern ne se reproduit pas dans les cycles suivants
- C'est le CLAUDE.md du projet, mais **auto-maintenu**
- Feedback loop : humain → commentaire → learning → meilleur code → moins de commentaires

## Principes de design

1. **Zero-click** — l'information vient a toi, pas l'inverse
2. **Visuel d'abord** — une video de 30s > un rapport de 30 lignes
3. **L'humain decide, TheSwarm execute** — approval flow, pas d'autonomie totale
4. **Memoire vivante** — les agents apprennent sans qu'on leur demande
5. **Pluggable** — tout est un adaptateur (chat, tickets, VCS, CI)
6. **Un TheSwarm par projet** — chaque repo a son equipe avec son contexte

## Stack technique

| Composant | Technologie | Status |
|-----------|-------------|--------|
| Orchestration | LangGraph (StateGraph) | ✅ En prod |
| Dev backend | Claude Code (Anthropic SDK) | ✅ En prod |
| VCS | PyGithub + git CLI | ✅ En prod |
| Chat | Mattermost (mattermostdriver) | ✅ En prod |
| Web framework | FastAPI + uvicorn | ✅ En prod |
| Browser automation | Playwright | 🔜 Milestone 1 |
| Video/screenshot | Playwright + ffmpeg | 🔜 Milestone 1 |
| Rapport visuel | HTML statique auto-genere | 🔜 Milestone 2 |
| Memoire | Structured markdown + retrospective | 🔜 Milestone 3 |
| API | FastAPI REST | 🔜 Milestone 4 |
| Ticket sources | Protocol + adaptateurs | 🔜 Milestone 5 |

## Repos

| Repo | Role |
|------|------|
| [jrechet/theswarm](https://github.com/jrechet/theswarm) | TheSwarm — equipe de dev autonome |
| [jrechet/swarm-bots](https://github.com/jrechet/swarm-bots) | Platform Agents (Logan, Coddy, etc.) — ops bots pour espace-client |
