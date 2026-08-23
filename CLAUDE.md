# CLAUDE.md

@AGENTS.md

Claude Code specifics on top of the shared guide above:

- Prod URL is `https://bots.jrec.fr/swarm` (NOT `jrec.fr/swarm`). Trigger a cycle
  with `POST /swarm/api/cycle {"repo": "jrechet/concert-tour-app"}` and follow it
  via `GET /swarm/api/cycles/{id}` or the dashboard.
- Prefer Seq (`logs.jrec.fr`) over `gh run watch` to verify a deploy; the deploy
  signal is the service image tag matching the main commit SHA.
- When touching `agents/*.py`, run the schema guard early:
  `uv run pytest tests/test_agent_state_schema.py -p no:playwright`.
- `docs/plans/` holds historical sprint plans (opus7, theswarm-04/05,
  the-bigger-swarm) — context only, not current truth.
