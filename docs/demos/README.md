# TheSwarm — committed demo videos

Per the plan rule (§4 of [`theswarm-04.md`](../../theswarm-04.md)):

> Chaque nouvelle feature ships avec une démo vidéo commitée en
> `docs/demos/<feature>.webm` ou dans le store. Pas de démo = pas de merge.

## Index

| File | Sprint | Covers |
|------|--------|--------|
| [`sprint-A.webm`](sprint-A.webm) | A — Fondations démo push | F1 SSE toast + Mattermost DM, F2 before/after, F3 walkthrough video, F4 thumbnail + GIF |

## Regenerating the self-demo

Sprint-A's `sprint-A.webm` is a placeholder generated at sprint close via the
bundled `imageio-ffmpeg` binary. To regenerate a richer self-demo (recommended
once the live server is running):

```bash
uv run python -m theswarm serve &
# trigger a cycle from the dashboard, open /demos/{id}/play
# record the screen with PlaywrightRecorder or QuickTime
```

Then overwrite this file with the captured webm.
