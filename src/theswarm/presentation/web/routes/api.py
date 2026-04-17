"""REST API routes — v2 queries + headless cycle management + live state."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.list_projects import ListProjectsQuery
from theswarm.presentation.web.sse import SSEHub

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ── V2 queries ──────────────────────────────────────────────────────


@router.get("/projects")
async def api_projects(request: Request) -> JSONResponse:
    query: ListProjectsQuery = request.app.state.list_projects_query
    projects = await query.execute()
    return JSONResponse([
        {
            "id": p.id,
            "repo": p.repo,
            "framework": p.framework,
            "ticket_source": p.ticket_source,
        }
        for p in projects
    ])


@router.get("/dashboard")
async def api_dashboard(request: Request) -> JSONResponse:
    query: GetDashboardQuery = request.app.state.get_dashboard_query
    dto = await query.execute()
    return JSONResponse({
        "active_cycles": len(dto.active_cycles),
        "projects": len(dto.projects),
        "total_cost_today": dto.total_cost_today,
    })


@router.get("/events")
async def sse_stream(request: Request) -> StreamingResponse:
    """SSE endpoint for real-time updates."""
    hub: SSEHub = request.app.state.sse_hub
    queue = hub.connect()
    return StreamingResponse(
        hub.event_stream(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Feature inventory ──────────────────────────────────────────────


_FEATURES = [
    {
        "id": "hashline",
        "name": "Hashline Edit Tool",
        "phase": 1,
        "module": "theswarm.tools.hashline",
        "description": "Hash-anchored file editing that prevents stale-line errors",
    },
    {
        "id": "ralph_loop",
        "name": "Ralph Loop",
        "phase": 1,
        "module": "theswarm.agents.dev",
        "description": "Persistent retry loop when quality gates fail (conditional graph edge)",
    },
    {
        "id": "watchdog",
        "name": "Todo Enforcer Watchdog",
        "phase": 1,
        "module": "theswarm.application.services.watchdog",
        "description": "Idle agent detection with configurable threshold and escalation",
    },
    {
        "id": "condenser",
        "name": "Context Condensation",
        "phase": 2,
        "module": "theswarm.tools.condenser",
        "description": "LLM-powered context summarization using Haiku to stay within token budgets",
    },
    {
        "id": "agents_md",
        "name": "AGENTS.md Generator",
        "phase": 2,
        "module": "theswarm.tools.agents_md",
        "description": "Auto-generates documentation by introspecting agent graph modules",
    },
    {
        "id": "mcp_skills",
        "name": "Skill-Embedded MCPs",
        "phase": 2,
        "module": "theswarm.infrastructure.mcp",
        "description": "Mount/unmount skill manifests per task category",
    },
    {
        "id": "model_routing",
        "name": "Model Routing Table",
        "phase": 2,
        "module": "theswarm.config",
        "description": "Task category to model mapping (Haiku for cheap, Sonnet for code)",
    },
    {
        "id": "intent_gate",
        "name": "IntentGate Enhancement",
        "phase": 2,
        "module": "theswarm.presentation.web.server",
        "description": "Haiku-powered NLU with param extraction and keyword fast path",
    },
    {
        "id": "sandbox",
        "name": "Sandbox Protocol",
        "phase": 3,
        "module": "theswarm.infrastructure.sandbox",
        "description": "Pluggable execution backend (local, Docker, OpenHands)",
    },
    {
        "id": "ast_grep",
        "name": "AST-Grep Tool",
        "phase": 3,
        "module": "theswarm.tools.ast_grep",
        "description": "Structural code search via ast-grep CLI wrapper",
    },
]


@router.get("/features")
async def api_features() -> JSONResponse:
    """List all platform features with availability status."""
    import importlib

    results = []
    for feat in _FEATURES:
        available = False
        try:
            importlib.import_module(feat["module"])
            available = True
        except ImportError:
            pass
        results.append({**feat, "available": available})
    return JSONResponse(results)


# ── Live cycle state (migrated from legacy dashboard) ───────────────


@router.get("/live/state")
async def live_state() -> JSONResponse:
    """Current cycle state (running, phase, cost, recent events)."""
    from theswarm.dashboard import get_dashboard_state
    return JSONResponse(get_dashboard_state().to_json())


@router.get("/live/events")
async def live_sse(request: Request) -> StreamingResponse:
    """SSE stream of live cycle events (role/message pairs)."""
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    queue = state.subscribe()

    async def event_stream():
        try:
            yield f"data: {json.dumps(state.to_json())}\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                if await request.is_disconnected():
                    break
        finally:
            state.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/live/history")
async def live_history() -> JSONResponse:
    """Cycle history from the target repo's cycle-history.jsonl."""
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    if not state.github_repo:
        return JSONResponse({"history": [], "note": "No repo configured"})
    try:
        from theswarm.tools.github import GitHubClient
        from theswarm.cycle_log import read_cycle_history
        github = GitHubClient(state.github_repo)
        entries = await read_cycle_history(github, limit=50)
        return JSONResponse({"history": entries})
    except Exception:
        log.exception("Failed to read cycle history")
        return JSONResponse({"history": [], "error": "Failed to read history"})


# ── Headless cycle API (migrated from legacy api.py) ────────────────


@router.get("/cycles/{cycle_id}")
async def api_cycle(request: Request, cycle_id: str) -> JSONResponse:
    """Get cycle status — checks v2 SQLite first, falls back to in-memory tracker."""
    # Try v2 repo first
    query: GetCycleStatusQuery = request.app.state.get_cycle_status_query
    cycle = await query.execute(cycle_id)
    if cycle is not None:
        return JSONResponse({
            "id": cycle.id,
            "project_id": cycle.project_id,
            "status": cycle.status,
            "triggered_by": cycle.triggered_by,
            "total_cost_usd": cycle.total_cost_usd,
            "phases": len(cycle.phases),
        })
    # Fall back to in-memory tracker
    from theswarm.api import get_cycle_tracker
    tracker = get_cycle_tracker()
    record = tracker.get(cycle_id)
    if record:
        return JSONResponse(record.model_dump())
    return JSONResponse({"error": "not found"}, status_code=404)


@router.get("/cycles")
async def api_list_cycles(limit: int = 20) -> JSONResponse:
    """List recent cycles from the in-memory tracker."""
    from theswarm.api import get_cycle_tracker
    tracker = get_cycle_tracker()
    records = tracker.list_recent(limit=min(limit, 100))
    return JSONResponse({"cycles": [r.model_dump() for r in records]})


@router.post("/cycle")
async def start_cycle(request: Request) -> JSONResponse:
    """Start a new cycle via the headless API."""
    from pydantic import ValidationError

    from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")
    try:
        req = CycleRequest(**body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    except TypeError as e:
        raise HTTPException(status_code=422, detail=str(e))

    tracker = get_cycle_tracker()
    record = tracker.create(req)

    allowed_repos = getattr(request.app.state, "allowed_repos", [])
    event_bus = getattr(request.app.state, "event_bus", None)
    task = asyncio.create_task(
        run_api_cycle(record.id, req.repo, req.description, req.callback_url, allowed_repos, event_bus=event_bus)
    )
    tracker.set_task(record.id, task)

    return JSONResponse({
        "cycle_id": record.id,
        "status": record.status.value,
        "repo": record.repo,
    })


@router.post("/cycle/{cycle_id}/cancel")
async def cancel_cycle(cycle_id: str) -> JSONResponse:
    """Cancel a running cycle."""
    from theswarm.api import CycleStatus, get_cycle_tracker

    tracker = get_cycle_tracker()
    record = tracker.get(cycle_id)
    if not record:
        raise HTTPException(status_code=404, detail="Cycle not found")
    if record.status not in (CycleStatus.QUEUED, CycleStatus.RUNNING):
        raise HTTPException(status_code=409, detail=f"Cycle is {record.status.value}")
    cancelled = tracker.cancel(cycle_id)
    return JSONResponse({"cancelled": cancelled, "cycle_id": cycle_id})


# ── Cycle reports (migrated from legacy dashboard) ──────────────────


@router.get("/reports/weekly")
async def weekly_report() -> JSONResponse:
    """Weekly summary from cycle history."""
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    if not state.github_repo:
        raise HTTPException(status_code=404, detail="No repo configured")
    try:
        from theswarm.tools.github import GitHubClient
        from theswarm.cycle_log import read_cycle_history
        github = GitHubClient(state.github_repo)
        entries = await read_cycle_history(github, limit=7)
        return JSONResponse({"entries": entries})
    except Exception:
        log.exception("Failed to generate weekly report")
        raise HTTPException(status_code=500, detail="Failed to generate weekly report")


@router.get("/reports/{date}")
async def api_report_by_date(date: str) -> JSONResponse:
    """Get a cycle report by date."""
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    result = state.reports.get(date)
    if not result:
        raise HTTPException(status_code=404, detail=f"No report for {date}")
    return JSONResponse(result)


@router.post("/reports/{date}/approve/{pr_number}")
async def approve_pr(date: str, pr_number: int) -> JSONResponse:
    """Approve and merge a PR from a cycle report."""
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    if not state.github_repo:
        raise HTTPException(status_code=400, detail="No repo configured")
    try:
        from theswarm.tools.github import GitHubClient
        github = GitHubClient(state.github_repo)
        await github.merge_pr(pr_number)
        return JSONResponse({"merged": True, "pr_number": pr_number})
    except Exception as e:
        log.exception("Failed to merge PR #%d", pr_number)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reports/{date}/comment/{pr_number}")
async def comment_on_pr(date: str, pr_number: int, request: Request) -> JSONResponse:
    """Post a review comment on a PR."""
    from theswarm.dashboard import get_dashboard_state
    state = get_dashboard_state()
    if not state.github_repo:
        raise HTTPException(status_code=400, detail="No repo configured")
    body = await request.json()
    comment = body.get("comment", "")
    if not comment:
        raise HTTPException(status_code=400, detail="No comment provided")
    try:
        from theswarm.tools.github import GitHubClient
        github = GitHubClient(state.github_repo)
        await github.create_pr_comment(pr_number, comment)
        return JSONResponse({"posted": True, "pr_number": pr_number})
    except Exception as e:
        log.exception("Failed to comment on PR #%d", pr_number)
        raise HTTPException(status_code=500, detail=str(e))
