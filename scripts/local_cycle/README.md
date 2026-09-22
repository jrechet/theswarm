# Faire tourner un cycle en local, sur le dépôt de la swarm

Le harnais utilisé pour la série de sept cycles locaux du 19 au 22 septembre 2026
(voir `docs/handoffs/2026-09-22-local-cycle-series-and-v2-handoff.md`).

```bash
bash scripts/local_cycle/run-targeted.sh 162     # un cycle ciblé sur l'issue #162
```

Ce que ça fait : source `.env` (ou `$SWARM_ENV_FILE`), épingle
`SWARM_GITHUB_REPO=jrechet/theswarm`, met l'espace de travail dans
`tmp/local-cycle/workspace`, refuse de démarrer si `claude -p` ne répond pas, et
journalise dans `tmp/local-cycle/targeted-<issue>-<horodatage>.log`.

**Pourquoi un cycle ciblé et pas `python -m theswarm run-cycle`** : sans
`target_issue`, le TechLead découpe tout le backlog — ~220 s par issue dans une
phase de 600 s — et ne peut pas finir sur ce dépôt. `targeted_cycle.py` construit
`CycleConfig(target_issue=N)`, exactement ce que fait le bouton ▶ Play en prod.

Prérequis côté machine : un `CLAUDE_CODE_OAUTH_TOKEN` valide dans `.env`
(`claude setup-token`), un `GITHUB_TOKEN` qui lit le dépôt, aucun hook `Stop`
Claude Code actif (il se déclenche dans chaque `claude -p` de la swarm et vide
les revues de leur verdict — voir AGENTS.md).
