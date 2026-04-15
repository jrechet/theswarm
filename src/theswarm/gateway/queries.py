"""Read-only queries — plan, report, issues."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theswarm.gateway.app import SwarmGateway

log = logging.getLogger(__name__)


def _get_vcs(gw: SwarmGateway, repo: str = ""):
    """Get the VCS object for a specific repo, or fall back to default."""
    if repo:
        vcs_map = getattr(gw, "_swarm_po_vcs_map", {})
        vcs = vcs_map.get(repo)
        if vcs:
            return vcs
    return gw._swarm_po_github


async def get_plan(gw: SwarmGateway, repo: str = "") -> str | None:
    """Fetch today's daily plan from the target repo."""
    vcs = _get_vcs(gw, repo)
    if not vcs:
        return None
    try:
        from datetime import date
        path = f"docs/daily-plans/{date.today().isoformat()}.md"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: vcs.get_file_content(path))
    except Exception:
        return None


async def get_report(gw: SwarmGateway, repo: str = "") -> str | None:
    """Fetch the latest daily report from the target repo."""
    vcs = _get_vcs(gw, repo)
    if not vcs:
        return None
    try:
        from datetime import date
        path = f"docs/daily-reports/{date.today().isoformat()}.md"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: vcs.get_file_content(path))
    except Exception:
        return None


async def list_issues(gw: SwarmGateway, repo: str = "") -> list[dict]:
    """List open issues for the specified repo."""
    vcs = _get_vcs(gw, repo)
    if not vcs:
        return []
    try:
        loop = asyncio.get_running_loop()
        issues = await loop.run_in_executor(None, lambda: vcs.list_issues(state="open"))
        return [{"number": i.number, "title": i.title, "labels": [{"name": l} for l in i.labels]} for i in issues]
    except Exception:
        log.exception("SwarmPO: failed to list issues")
        return []
