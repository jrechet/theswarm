"""Run one targeted cycle locally — the same shape the Play button uses.

`python -m theswarm run-cycle` runs the *daily* cycle: no `target_issue`, so
the TechLead breakdown walks the whole backlog, one ~220s Claude call per
issue, inside a 600s phase. On this repository that cannot fit. The web API
(`api.py`) sets `target_issue`, which scopes the breakdown to one issue and
its children — that is the flow production measures, so it is the flow to
reproduce here.

Usage: targeted_cycle.py <issue_number>
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle

REPO = "jrechet/theswarm"


async def main(issue: int) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = CycleConfig(
        github_repo=REPO,
        project_id=REPO,
        target_issue=issue,
        team_id="local",
        workspace_dir=os.environ["SWARM_WORKSPACE_DIR"],
    )

    print(f"\n{'=' * 60}")
    print(f"TARGETED CYCLE — {REPO} #{issue}")
    print(f"{'=' * 60}\n")

    result = await run_daily_cycle(config)

    print(f"\n{'=' * 60}")
    for key in ("cost_usd", "prs", "prs_merged", "held_prs", "reviews",
                "demo_report", "daily_report"):
        if key in result:
            value = result[key]
            if key in ("demo_report", "daily_report"):
                value = f"<{len(str(value))} chars>" if value else "(none)"
            print(f"  {key:<14} {value}")
    print(f"{'=' * 60}\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(int(sys.argv[1]))))
