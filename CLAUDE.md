# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

Claude Code specifics on top of the shared guide above:

- Prod URL is `https://bots.jrec.fr/swarm` (NOT `jrec.fr/swarm`, NOT the bare
  domain — both 404). Every route is behind the auth wall: API calls need
  `Authorization: Bearer $SWARM_ACCESS_KEY` (on the server:
  `ssh -p5422 debian@jrec.fr cat swarm-access-key.txt` — never paste it into
  chat or files). Trigger a cycle with
  `POST /swarm/api/cycle {"repo": "jrechet/concert-tour-app", "issue_number": N}`
  and follow it at `/swarm/c/{cycle_id}` (the theater) or `GET /swarm/api/cycles/{id}`.
- Prefer Seq (`logs.jrec.fr`) over `gh run watch` to verify a deploy; the deploy
  signal is the service image tag matching the main commit SHA. Auto-merge is
  disabled on the repo: `gh pr merge <n> --squash` once CI is green. A ~2 min
  window of 404s during the rolling update is normal — wait for the task to be
  `Running` and `/health` to answer 200 before judging.
- After touching `templates/v2/**` or `static/v2/input.css`, run
  `bash scripts/build-css.sh` (fetches the pinned Tailwind binary into
  `./tmp/bin`). `static/v2/app.css` is generated and gitignored; the Docker
  `css` stage builds it for prod.
- When touching `agents/*.py`, run the schema guard early:
  `uv run pytest tests/test_agent_state_schema.py -p no:playwright`.
- Web tests run with the auth wall down (`SWARM_AUTH_DISABLED=1`, set
  suite-wide in `tests/conftest.py`). A test that needs the wall re-enables it
  with `monkeypatch.setenv("SWARM_AUTH_DISABLED", "")`. One test:
  `uv run pytest tests/presentation/test_auth_wall.py::test_name -p no:playwright`.
- `docs/plans/2026-09-v2-one-flow.md` is the current plan; everything else in
  `docs/plans/` (opus7, theswarm-04/05, the-bigger-swarm) is history, not truth.
  `docs/handoffs/` holds open investigations — read the latest before touching
  the GitHub App setup. `docs/DEPENDENCIES.md` is the owner's visual dependency
  map: any new external dependency, credential or CDN is a shared decision and
  gets a row there before it ships.
