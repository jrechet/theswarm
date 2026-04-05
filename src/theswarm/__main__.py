"""Entry point: python -m theswarm [--cycle | --dev-only | --techlead-only]"""

from __future__ import annotations

import asyncio
import logging
import sys

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle, run_dev_only, run_techlead_only


def main() -> None:
    args = sys.argv[1:]

    # Server mode (default, no flags)
    if not args:
        from theswarm.main import main as server_main
        server_main()
        return

    # CLI Cycle modes
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = CycleConfig.from_env()

    if not config.is_real_mode and ("--dev-only" in args or "--techlead-only" in args or "--cycle" in args):
        print("ERROR: agent-only modes require SWARM_GITHUB_REPO to be set")
        sys.exit(1)

    if not config.is_real_mode:
        print("Running in STUB mode (no SWARM_GITHUB_REPO set)")
        print("Set SWARM_GITHUB_REPO=owner/repo to run for real.\n")

    if "--dev-only" in args:
        print(f"Mode: DEV ONLY — repo: {config.github_repo}")
        print(f"Workspace: {config.workspace_dir}\n")
        result = asyncio.run(run_dev_only(config))
    elif "--techlead-only" in args:
        print(f"Mode: TECHLEAD ONLY — repo: {config.github_repo}\n")
        result = asyncio.run(run_techlead_only(config))
    elif "--cycle" in args:
        print(f"Mode: DAILY CYCLE — repo: {config.github_repo}\n")
        result = asyncio.run(run_daily_cycle(config))
    else:
        print(f"Unknown arguments: {args}")
        print("Usage: python -m theswarm [--cycle | --dev-only | --techlead-only]")
        sys.exit(1)

    print(f"\nDone. Total cost: ${result['cost_usd']:.2f}")


if __name__ == "__main__":
    main()
