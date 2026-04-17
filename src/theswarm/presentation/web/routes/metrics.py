"""Prometheus-compatible /metrics endpoint.

Exposes counters and gauges scraped from the project and cycle repos so an
external Prometheus can track TheSwarm's activity without pulling SQLite
directly.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from theswarm.domain.cycles.value_objects import CycleStatus

router = APIRouter()

_PROCESS_START = time.time()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    project_repo = getattr(request.app.state, "project_repo", None)
    cycle_repo = getattr(request.app.state, "cycle_repo", None)

    projects_total = 0
    if project_repo is not None:
        try:
            projects = await project_repo.list_all()
            projects_total = len(projects)
        except Exception:
            projects_total = 0

    cycles_running = 0
    cycles_completed = 0
    cycles_failed = 0
    cost_sum = 0.0
    tokens_sum = 0

    if cycle_repo is not None:
        try:
            recent = await cycle_repo.list_recent(limit=500)
        except Exception:
            recent = []
        for c in recent:
            raw_status = getattr(c, "status", None)
            status = raw_status if isinstance(raw_status, CycleStatus) else CycleStatus(raw_status)
            if status == CycleStatus.RUNNING:
                cycles_running += 1
            elif status == CycleStatus.COMPLETED:
                cycles_completed += 1
            elif status == CycleStatus.FAILED:
                cycles_failed += 1
            cost_sum += float(getattr(c, "total_cost_usd", 0.0) or 0.0)
            tokens_sum += int(getattr(c, "total_tokens", 0) or 0)

    uptime = time.time() - _PROCESS_START

    lines = [
        "# HELP theswarm_uptime_seconds Seconds since process start.",
        "# TYPE theswarm_uptime_seconds gauge",
        f"theswarm_uptime_seconds {uptime:.3f}",
        "# HELP theswarm_projects_total Registered projects.",
        "# TYPE theswarm_projects_total gauge",
        f"theswarm_projects_total {projects_total}",
        "# HELP theswarm_cycles Cycles grouped by status (recent window of 500).",
        "# TYPE theswarm_cycles gauge",
        f'theswarm_cycles{{status="running"}} {cycles_running}',
        f'theswarm_cycles{{status="completed"}} {cycles_completed}',
        f'theswarm_cycles{{status="failed"}} {cycles_failed}',
        "# HELP theswarm_cycle_cost_usd_sum Total cost across recent cycles.",
        "# TYPE theswarm_cycle_cost_usd_sum counter",
        f"theswarm_cycle_cost_usd_sum {cost_sum:.4f}",
        "# HELP theswarm_cycle_tokens_sum Total tokens across recent cycles.",
        "# TYPE theswarm_cycle_tokens_sum counter",
        f"theswarm_cycle_tokens_sum {tokens_sum}",
        "",
    ]
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
