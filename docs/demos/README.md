# TheSwarm — committed demo videos

Per the plan rule (§4 of [`theswarm-04.md`](../../theswarm-04.md)):

> Chaque nouvelle feature ships avec une démo vidéo commitée en
> `docs/demos/<feature>.webm` ou dans le store. Pas de démo = pas de merge.

## Index

| File | Sprint | Covers |
|------|--------|--------|
| [`sprint-A.webm`](sprint-A.webm) | A — Fondations démo push | F1 SSE toast + Mattermost DM, F2 before/after, F3 walkthrough video, F4 thumbnail + GIF |
| [`sprint-B.webm`](sprint-B.webm) | B — Controls in-dashboard | C1 config editor, C2 effort slider, C3 secret vault, C4 cost caps, C6 kill-switch |
| [`sprint-C.webm`](sprint-C.webm) | C — Approve/Reject inline + preview | F5 public demo URL, F6 inline approve/reject, F9 live preview iframe |
| [`sprint-D.webm`](sprint-D.webm) | D — Observabilité live & replay | V1 activity feed, V2 replay scrubber, V3 agent thoughts, V5 Web Push, C5 cost preview |
| [`sprint-E.webm`](sprint-E.webm) | E — Mémoire vivante & improver | M1 memory viewer, M2 retrospective, M4 Improver CLAUDE.md PR |
| [`sprint-F.webm`](sprint-F.webm) | F — Pluggabilité & polish | P1 webhook, P2 Linear adapter, M3 compaction, F7 speed, F8 comparator |
| [`sprint-G.webm`](sprint-G.webm) | G — Résilience & fail-safes | G1 checkpoints, G2 adaptive Claude, G3 GitHub breaker, G4 readiness, G5 resume UI |

## Recording / re-recording a walkthrough

Every sprint demo is a real Playwright capture of the dashboard tour, with
the per-sprint demo play page included in the stops. To re-record:

```bash
# one sprint
uv run python scripts/record_sprint_walkthrough.py B

# all of B-F in sequence
uv run python scripts/record_sprint_walkthrough.py all
```

The script boots an isolated TheSwarm server in a temp dir, runs `seed_self`
(so the full sprint history is populated), walks the key dashboard screens
and writes `docs/demos/sprint-<L>.webm`.

On deploy, the unified server runs `seed_self` at startup and copies the
committed webms into the artifact store, so every dashboard gets the
current recordings automatically. Set `SWARM_SKIP_SELF_SEED=1` to opt out.
