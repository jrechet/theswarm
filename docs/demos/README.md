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

## Regenerating a placeholder demo

Placeholders are short colored title-card webms generated via the bundled
`imageio-ffmpeg` binary. Example:

```bash
uv run python scripts/gen_sprint_demo.py G "Résilience & fail-safes"
```

To record a real walkthrough instead:

```bash
uv run python -m theswarm serve &
# trigger a cycle from the dashboard, open /demos/{id}/play
# record the screen with PlaywrightRecorder or QuickTime
```

Then overwrite the placeholder webm with the captured recording.
