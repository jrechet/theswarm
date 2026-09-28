"""Data for the demo to show: the target's `demo.seed` commands.

QA walks the pages a cycle's PRs added on a demo server started from the
workspace — and on concert-tour-app that server's database was empty:
/api/v1/concerts/1/occupancy answered 404 and was skipped, the dashboard
showed nothing (cycle 28371c2016da, docs/demos/v2-play-to-demo.webm).
A target declares how its demo gets data, in its theswarm.yaml:

    demo:
      seed:
        - "{python} scripts/seed_demo.py {url}"

Each command runs once the demo server answers, in the workspace, with
`{python}` (the workspace's interpreter), `{url}` and `{port}` filled in,
`DEMO_URL` in its environment, and the same scrubbed environment as the
launch: the target seeds itself through its own API, so it creates its
tables and validates its rows the way it always does. A failing or hung
command is logged and the demo goes on without it.

The two capture lanes launch two servers on one workspace — one database
file — so seeds on a workspace run one at a time: a seed that checks
"empty?" before writing must not race its twin. Seeding is the target's
to make idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

log = logging.getLogger(__name__)

DEMO_SEED_TIMEOUT_SECONDS = 120

# Per workspace and per event loop: an asyncio.Lock belongs to one loop.
_LOCKS: dict[tuple[str, int], asyncio.Lock] = {}


def _lock_for(workspace: str) -> asyncio.Lock:
    key = (workspace, id(asyncio.get_running_loop()))
    lock = _LOCKS.get(key)
    if lock is None:
        lock = _LOCKS[key] = asyncio.Lock()
    return lock


async def run_seed(
    workspace: str,
    commands: list | None,
    *,
    python: str,
    url: str,
    env: dict[str, str],
) -> list[tuple[str, int | None]]:
    """Run the declared seed commands; (command, exit code) each, None when
    it was cut off."""
    if not isinstance(commands, list) or not commands:
        return []
    port = str(urlparse(url).port or "")
    child_env = {**env, "DEMO_URL": url}
    outcomes: list[tuple[str, int | None]] = []
    async with _lock_for(workspace):
        for raw in commands:
            template = str(raw)
            command = template.replace("{python}", python).replace("{url}", url).replace("{port}", port)
            outcomes.append((template, await _run(command, workspace, child_env)))
    return outcomes


async def _run(command: str, workspace: str, env: dict[str, str]) -> int | None:
    proc = await asyncio.create_subprocess_shell(
        command, cwd=workspace, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=DEMO_SEED_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        log.warning("QA: demo seed timed out after %ss: %s", DEMO_SEED_TIMEOUT_SECONDS, command)
        return None
    if proc.returncode != 0:
        log.warning("QA: demo seed failed (rc=%s): %s\n%s", proc.returncode, command,
                    stdout.decode(errors="replace")[-1000:])
    else:
        log.info("QA: demo seed ran: %s", command)
    return proc.returncode
