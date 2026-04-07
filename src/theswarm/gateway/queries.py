"""Read-only queries — plan, report, issues."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theswarm.gateway.app import SwarmGateway

log = logging.getLogger(__name__)


async def get_plan(gw: SwarmGateway) -> str | None:
    """Fetch today's daily plan from the target repo."""
    vcs = gw._swarm_po_github
    if not vcs:
        return None
    try:
        from datetime import date
        path = f"docs/daily-plans/{date.today().isoformat()}.md"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: vcs.get_file_content(path))
    except Exception:
        return None


async def get_report(gw: SwarmGateway) -> str | None:
    """Fetch the latest daily report from the target repo."""
    vcs = gw._swarm_po_github
    if not vcs:
        return None
    try:
        from datetime import date
        path = f"docs/daily-reports/{date.today().isoformat()}.md"
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: vcs.get_file_content(path))
    except Exception:
        return None


async def list_issues(gw: SwarmGateway) -> list[dict]:
    """List open issues for the SWARM target repo."""
    vcs = gw._swarm_po_github
    if not vcs:
        return []
    try:
        loop = asyncio.get_running_loop()
        issues = await loop.run_in_executor(None, lambda: vcs.list_issues(state="open"))
        return [{"number": i.number, "title": i.title, "labels": [{"name": l} for l in i.labels]} for i in issues]
    except Exception:
        log.exception("SwarmPO: failed to list issues")
        return []
