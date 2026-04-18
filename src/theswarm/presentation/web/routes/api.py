"""REST API routes — v2 queries + headless cycle management + live state.

Every dashboard feature is also exposed here as JSON so AI agents can drive
the system end-to-end without parsing HTML.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery
from theswarm.application.queries.get_dashboard import GetDashboardQuery
from theswarm.application.queries.list_projects import ListProjectsQuery
from theswarm.presentation.web.sse import SSEHub

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    """Full dashboard snapshot — everything the HTML dashboard renders, as JSON."""
    query: GetDashboardQuery = request.app.state.get_dashboard_query
    dto = await query.execute()
    return JSONResponse({
        "active_cycles": [_cycle_dto_to_json(c) for c in dto.active_cycles],
        "recent_cycles": [_cycle_dto_to_json(c) for c in dto.recent_cycles],
        "recent_activities": [
            {
                "timestamp": a.timestamp,
                "project_id": a.project_id,
                "agent": a.agent,
                "action": a.action,
                "detail": a.detail,
                "metadata": a.metadata,
            }
            for a in dto.recent_activities
        ],
        "projects": [_project_dto_to_json(p) for p in dto.projects],
        "counts": {
            "active_cycles": len(dto.active_cycles),
            "projects": len(dto.projects),
        },
        "total_cost_today": dto.total_cost_today,
        "total_cost_week": dto.total_cost_week,
        "success_rate_7d": dto.success_rate_7d,
        "cycles_completed_7d": dto.cycles_completed_7d,
        "cycles_failed_7d": dto.cycles_failed_7d,
        "cost_per_day_7d": list(dto.cost_per_day_7d),
        "cycles_per_day_7d": list(dto.cycles_per_day_7d),
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


# ── JSON serializers ───────────────────────────────────────────────


def _project_dto_to_json(p) -> dict:
    return {
        "id": p.id,
        "repo": p.repo,
        "default_branch": p.default_branch,
        "framework": p.framework,
        "ticket_source": p.ticket_source,
        "team_channel": p.team_channel,
        "schedule": p.schedule,
        "test_command": p.test_command,
        "source_dir": p.source_dir,
        "max_daily_stories": p.max_daily_stories,
        "created_at": p.created_at,
    }


def _phase_dto_to_json(p) -> dict:
    return {
        "phase": p.phase,
        "agent": p.agent,
        "status": p.status,
        "started_at": p.started_at,
        "completed_at": p.completed_at,
        "tokens_used": p.tokens_used,
        "cost_usd": p.cost_usd,
        "summary": p.summary,
    }


def _cycle_dto_to_json(c) -> dict:
    # `phases` may be either PhaseDTO instances or SimpleNamespace tracker adapters.
    phases_out = []
    for p in c.phases:
        if hasattr(p, "started_at"):
            phases_out.append(_phase_dto_to_json(p))
    return {
        "id": c.id,
        "project_id": c.project_id,
        "status": c.status,
        "triggered_by": c.triggered_by,
        "started_at": c.started_at,
        "completed_at": c.completed_at,
        "total_tokens": c.total_tokens,
        "total_cost_usd": c.total_cost_usd,
        "prs_opened": list(c.prs_opened),
        "prs_merged": list(c.prs_merged),
        "phases": phases_out,
    }


def _artifact_to_json(a) -> dict:
    return {
        "type": a.type.value,
        "path": a.path,
        "label": a.label,
        "size_bytes": a.size_bytes,
    }


def _story_to_json(s) -> dict:
    return {
        "title": s.title,
        "ticket_id": s.ticket_id,
        "pr_number": s.pr_number,
        "pr_url": s.pr_url,
        "status": s.status,
        "files_changed": s.files_changed,
        "lines_added": s.lines_added,
        "lines_removed": s.lines_removed,
        "screenshots_before": [_artifact_to_json(a) for a in s.screenshots_before],
        "screenshots_after": [_artifact_to_json(a) for a in s.screenshots_after],
        "video": _artifact_to_json(s.video) if s.video else None,
        "diff_highlights": [
            {"file_path": d.file_path, "hunk": d.hunk, "annotation": d.annotation}
            for d in s.diff_highlights
        ],
    }


def _report_to_json(report, *, full: bool = False) -> dict:
    base = {
        "id": report.id,
        "cycle_id": str(report.cycle_id),
        "project_id": report.project_id,
        "created_at": report.created_at.isoformat(),
        "summary": {
            "stories_completed": report.summary.stories_completed,
            "stories_total": report.summary.stories_total,
            "prs_merged": report.summary.prs_merged,
            "tests_passing": report.summary.tests_passing,
            "tests_total": report.summary.tests_total,
            "coverage_percent": report.summary.coverage_percent,
            "security_critical": report.summary.security_critical,
            "security_medium": report.summary.security_medium,
            "cost_usd": report.summary.cost_usd,
        },
        "quality_gates": [
            {"name": g.name, "status": g.status.value, "detail": g.detail}
            for g in report.quality_gates
        ],
        "stories_count": len(report.stories),
        "artifacts_count": len(report.artifacts),
        "all_gates_pass": report.all_gates_pass,
    }
    if full:
        base["stories"] = [_story_to_json(s) for s in report.stories]
        base["artifacts"] = [_artifact_to_json(a) for a in report.artifacts]
        base["agent_learnings"] = list(report.agent_learnings)
    return base


# ── Project detail / create / delete ──────────────────────────────


@router.get("/projects/{project_id}")
async def api_project_detail(request: Request, project_id: str) -> JSONResponse:
    """Single project snapshot."""
    from theswarm.application.queries.get_project import GetProjectQuery
    query: GetProjectQuery = request.app.state.get_project_query
    project = await query.execute(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return JSONResponse(_project_dto_to_json(project))


@router.post("/projects", status_code=201)
async def api_create_project(request: Request) -> JSONResponse:
    """Create a project via JSON. Body: {project_id, repo, framework?, ticket_source?, team_channel?}."""
    from theswarm.application.commands.create_project import (
        CreateProjectCommand,
        CreateProjectHandler,
    )
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    project_id = body.get("project_id") or body.get("id")
    repo = body.get("repo")
    if not project_id or not repo:
        raise HTTPException(status_code=422, detail="project_id and repo are required")

    handler: CreateProjectHandler = request.app.state.create_project_handler
    try:
        await handler.handle(
            CreateProjectCommand(
                project_id=project_id,
                repo=repo,
                framework=body.get("framework", "auto"),
                ticket_source=body.get("ticket_source", "github"),
                team_channel=body.get("team_channel", ""),
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Return the created project
    from theswarm.application.queries.get_project import GetProjectQuery
    get_project: GetProjectQuery = request.app.state.get_project_query
    created = await get_project.execute(project_id)
    return JSONResponse(_project_dto_to_json(created) if created else {"id": project_id}, status_code=201)


@router.delete("/projects/{project_id}", status_code=204)
async def api_delete_project(request: Request, project_id: str):
    """Delete a project."""
    from fastapi import Response

    from theswarm.application.commands.delete_project import (
        DeleteProjectCommand,
        DeleteProjectHandler,
    )
    handler: DeleteProjectHandler = request.app.state.delete_project_handler
    try:
        await handler.handle(DeleteProjectCommand(project_id=project_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    return Response(status_code=204)


# ── Cycle listing (v2 repo + tracker merged) ───────────────────────


@router.get("/cycles-all")
async def api_cycles_all(
    request: Request,
    project_id: str = "",
    limit: int = 30,
) -> JSONResponse:
    """List cycles across v2 repo AND in-memory tracker, optionally filtered by project."""
    from theswarm.application.queries.list_cycles import ListCyclesQuery
    from theswarm.api import get_cycle_tracker

    query: ListCyclesQuery = request.app.state.list_cycles_query
    v2_cycles = await query.execute(project_id, limit=min(limit, 100))
    v2_ids = {c.id for c in v2_cycles}

    tracker_cycles = []
    for record in get_cycle_tracker().list_recent(limit=min(limit, 100)):
        if record.id in v2_ids:
            continue
        if project_id and record.repo != project_id:
            continue
        tracker_cycles.append({
            "id": record.id,
            "project_id": record.repo,
            "status": record.status.value,
            "triggered_by": "web",
            "started_at": record.started_at,
            "completed_at": record.completed_at,
            "total_tokens": record.result.get("total_tokens", 0) if record.result else 0,
            "total_cost_usd": record.result.get("cost_usd", 0.0) if record.result else 0.0,
            "prs_opened": record.result.get("prs_opened", []) if record.result else [],
            "prs_merged": record.result.get("prs_merged", []) if record.result else [],
            "phases": [],
        })

    merged = [_cycle_dto_to_json(c) for c in v2_cycles] + tracker_cycles
    return JSONResponse({"cycles": merged, "count": len(merged)})


@router.post("/projects/{project_id}/cycle", status_code=202)
async def api_trigger_cycle_for_project(request: Request, project_id: str) -> JSONResponse:
    """Trigger a cycle by project_id (resolves repo automatically)."""
    from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle
    from theswarm.application.queries.get_project import GetProjectQuery

    get_project: GetProjectQuery = request.app.state.get_project_query
    project = await get_project.execute(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    description = body.get("description") or f"API-triggered cycle for {project_id}"
    callback_url = body.get("callback_url", "")

    tracker = get_cycle_tracker()
    req = CycleRequest(repo=str(project.repo), description=description, callback_url=callback_url)
    record = tracker.create(req)

    allowed_repos = getattr(request.app.state, "allowed_repos", [])
    event_bus = getattr(request.app.state, "event_bus", None)
    task = asyncio.create_task(
        run_api_cycle(
            record.id, str(project.repo), description, callback_url,
            allowed_repos, event_bus=event_bus,
        ),
    )
    tracker.set_task(record.id, task)

    return JSONResponse({
        "cycle_id": record.id,
        "status": record.status.value,
        "project_id": project_id,
        "repo": record.repo,
    }, status_code=202)


# ── Reports (list + by-id, alongside legacy date-based) ────────────


@router.get("/reports")
async def api_list_reports(
    request: Request,
    project_id: str = "",
    limit: int = 30,
) -> JSONResponse:
    """List demo reports — newest first, optionally filtered by project_id."""
    report_repo = getattr(request.app.state, "report_repo", None)
    if report_repo is None:
        return JSONResponse({"reports": [], "error": "reports not configured"}, status_code=501)

    limit = max(1, min(limit, 200))
    if project_id:
        reports = await report_repo.list_by_project(project_id, limit=limit)
    else:
        reports = await report_repo.list_recent(limit=limit)
    return JSONResponse({
        "reports": [_report_to_json(r) for r in reports],
        "count": len(reports),
    })


@router.get("/reports/id/{report_id}")
async def api_get_report_by_id(request: Request, report_id: str) -> JSONResponse:
    """Fetch a single demo report by ID (full payload including stories+artifacts)."""
    report_repo = getattr(request.app.state, "report_repo", None)
    if report_repo is None:
        raise HTTPException(status_code=501, detail="reports not configured")
    report = await report_repo.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return JSONResponse(_report_to_json(report, full=True))


# ── Demos ──────────────────────────────────────────────────────────


@router.get("/demos")
async def api_list_demos(
    request: Request,
    project: str = "",
    since: str = "",
    limit: int = 50,
) -> JSONResponse:
    """List demos, optionally filtered by project and date (YYYY-MM-DD)."""
    from datetime import datetime, timezone

    report_repo = getattr(request.app.state, "report_repo", None)
    if report_repo is None:
        return JSONResponse({"demos_by_project": {}, "total": 0}, status_code=200)

    since_dt = None
    if since:
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=422, detail="since must be YYYY-MM-DD")

    limit = max(1, min(limit, 200))
    list_projects_query = request.app.state.list_projects_query
    projects = await list_projects_query.execute()
    target_ids = [project] if project else [p.id for p in projects]

    demos_by_project: dict[str, list] = {}
    for pid in target_ids:
        reports = await report_repo.list_by_project(pid, limit=limit)
        if since_dt is not None:
            reports = [r for r in reports if r.created_at >= since_dt]
        if reports:
            demos_by_project[pid] = [_report_to_json(r) for r in reports]

    if not project:
        known = {p.id for p in projects}
        recent = await report_repo.list_recent(limit=200)
        for r in recent:
            if r.project_id in known:
                continue
            if since_dt is not None and r.created_at < since_dt:
                continue
            demos_by_project.setdefault(r.project_id, []).append(_report_to_json(r))

    total = sum(len(v) for v in demos_by_project.values())
    return JSONResponse({
        "demos_by_project": demos_by_project,
        "total": total,
        "project_filter": project,
        "since": since,
    })


@router.get("/demos/{report_id}")
async def api_get_demo(request: Request, report_id: str) -> JSONResponse:
    """Full demo payload including stories and artifacts — used by the demo player and agents."""
    report_repo = getattr(request.app.state, "report_repo", None)
    if report_repo is None:
        raise HTTPException(status_code=501, detail="reports not configured")
    report = await report_repo.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="demo not found")
    return JSONResponse(_report_to_json(report, full=True))


# ── Schedules ──────────────────────────────────────────────────────


@router.get("/schedules")
async def api_list_schedules(request: Request) -> JSONResponse:
    """List all enabled schedules."""
    query = getattr(request.app.state, "list_schedules_query", None)
    if query is None:
        return JSONResponse({"schedules": [], "error": "schedules not configured"}, status_code=501)
    schedules = await query.execute()
    return JSONResponse({
        "schedules": [
            {
                "project_id": s.project_id,
                "cron": s.cron,
                "enabled": s.enabled,
                "last_run": s.last_run,
                "next_run": s.next_run,
            }
            for s in schedules
        ],
        "count": len(schedules),
    })


@router.get("/schedules/{project_id}")
async def api_get_schedule(request: Request, project_id: str) -> JSONResponse:
    """Get schedule for a project."""
    query = getattr(request.app.state, "get_schedule_query", None)
    if query is None:
        raise HTTPException(status_code=501, detail="schedules not configured")
    schedule = await query.execute(project_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="no schedule for project")
    return JSONResponse({
        "project_id": schedule.project_id,
        "cron": schedule.cron,
        "enabled": schedule.enabled,
        "last_run": schedule.last_run,
        "next_run": schedule.next_run,
    })


@router.put("/schedules/{project_id}")
async def api_set_schedule(request: Request, project_id: str) -> JSONResponse:
    """Set/update a schedule. Body: {cron: "0 8 * * 1-5", enabled?: bool}."""
    from theswarm.application.commands.manage_schedule import (
        SetScheduleCommand,
        SetScheduleHandler,
    )
    handler: SetScheduleHandler | None = getattr(request.app.state, "set_schedule_handler", None)
    if handler is None:
        raise HTTPException(status_code=501, detail="schedules not configured")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    cron = body.get("cron")
    if not cron:
        raise HTTPException(status_code=422, detail="cron is required")
    enabled = bool(body.get("enabled", True))
    from theswarm.domain.scheduling.value_objects import CronExpression
    try:
        CronExpression(cron)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        schedule = await handler.handle(
            SetScheduleCommand(project_id=project_id, cron=cron, enabled=enabled),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return JSONResponse({
        "project_id": schedule.project_id,
        "cron": str(schedule.cron),
        "enabled": schedule.enabled,
        "last_run": schedule.last_run.isoformat() if schedule.last_run else None,
        "next_run": schedule.next_run.isoformat() if schedule.next_run else None,
    })


@router.delete("/schedules/{project_id}", status_code=204)
async def api_delete_schedule(request: Request, project_id: str):
    """Delete a schedule for a project."""
    from fastapi import Response

    from theswarm.application.commands.manage_schedule import (
        DeleteScheduleCommand,
        DeleteScheduleHandler,
    )
    handler: DeleteScheduleHandler | None = getattr(
        request.app.state, "delete_schedule_handler", None,
    )
    if handler is None:
        raise HTTPException(status_code=501, detail="schedules not configured")
    try:
        await handler.handle(DeleteScheduleCommand(project_id=project_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="no schedule for project")
    return Response(status_code=204)


# ── Activities ─────────────────────────────────────────────────────


@router.get("/activities")
async def api_activities(
    request: Request,
    project_id: str = "",
    limit: int = 50,
) -> JSONResponse:
    """Recent agent activity feed."""
    activity_repo = getattr(request.app.state, "activity_repo", None)
    if activity_repo is None:
        return JSONResponse({"activities": [], "count": 0})
    limit = max(1, min(limit, 200))
    try:
        records = await activity_repo.list_recent(limit=limit)
    except Exception:
        log.exception("Failed to read activities")
        return JSONResponse({"activities": [], "count": 0, "error": "activity read failed"})
    if project_id:
        records = [r for r in records if r.get("project_id") == project_id]
    return JSONResponse({"activities": records, "count": len(records)})
