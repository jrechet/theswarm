"""DevOps (D1): the last report as JSON, and a refresh — the owner's only.

`/api/*` is the owner's by the wall; `/ops/refresh` is the Ops card's
button (a member's session never matches it).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter()


def _watch(request: Request):
    return getattr(request.app.state, "ops_watch", None)


@router.get("/api/devops")
async def api_devops(request: Request) -> JSONResponse:
    watch = _watch(request)
    if watch is None:
        return JSONResponse({"detail": "DevOps is not configured (no stack declared)"}, status_code=404)
    report = await watch.latest()
    return JSONResponse({**report.as_dict(), "error": watch.error, "posted_on": str(watch.posted_on or "")})


@router.post("/api/devops/refresh")
async def api_devops_refresh(request: Request) -> JSONResponse:
    watch = _watch(request)
    if watch is None:
        return JSONResponse({"detail": "DevOps is not configured (no stack declared)"}, status_code=404)
    report = await watch.refresh()
    return JSONResponse({**report.as_dict(), "error": watch.error})


@router.post("/api/devops/preflight")
async def api_devops_preflight(request: Request) -> JSONResponse:
    """Go or no-go for a cycle about to start (D2): the harness asks before
    it opens an issue; a server without a stack says go with nothing read."""
    watch = _watch(request)
    if watch is None:
        return JSONResponse({"go": True, "reasons": [], "word": "go (no stack declared)", "findings": []})
    answer = await watch.preflight()
    return JSONResponse(answer.as_dict())


@router.post("/ops/improve")
async def ops_improve(request: Request) -> RedirectResponse:
    """The owner's click (D4): DevOps measures, asks, opens the PR in the background; the card follows."""
    from theswarm.presentation.web.routes.customers import current_actor

    watch = _watch(request)
    actor = await current_actor(request)
    base = request.app.state.base_path
    if watch is not None and actor is not None and actor.is_owner and watch.can_improve:
        watch.start_improvement()
    return RedirectResponse(f"{base}/#ops", status_code=303)


@router.get("/api/devops/improvement")
async def api_improvement(request: Request) -> JSONResponse:
    watch = _watch(request)
    if watch is None:
        return JSONResponse({"detail": "DevOps is not configured (no stack declared)"}, status_code=404)
    report = watch.last()
    return JSONResponse({"improvement": watch.improvement, "can_improve": watch.can_improve,
                         "open_prs": list((report.facts.get("devops_prs") if report else None) or [])})


@router.get("/api/devops/proposals")
async def api_proposals(request: Request) -> JSONResponse:
    service = getattr(request.app.state, "proposal_service", None)
    if service is None:
        return JSONResponse({"open": [], "recent": []})
    return JSONResponse({"open": [proposal_dict(p) for p in await service.open()],
                         "recent": [proposal_dict(p) for p in await service.recent()]})


@router.post("/ops/proposals/{proposal_id}/{decision}")
async def decide_proposal(request: Request, proposal_id: str, decision: str) -> RedirectResponse:
    """The owner's one click on the home: approve runs the command on the host now, refuse keeps the no."""
    from theswarm.presentation.web.routes.customers import current_actor

    service = getattr(request.app.state, "proposal_service", None)
    actor = await current_actor(request)
    base = request.app.state.base_path
    if service is None or actor is None or not actor.is_owner or decision not in ("approve", "refuse"):
        return RedirectResponse(f"{base}/#ops", status_code=303)
    if decision == "approve":
        await service.approve(proposal_id, by=actor.login)
    else:
        await service.refuse(proposal_id, by=actor.login)
    return RedirectResponse(f"{base}/#ops", status_code=303)


def proposal_dict(p) -> dict:
    return {"id": p.id, "kind": p.kind, "host": p.host, "title": p.title, "why": p.why, "command": p.command,
            "status": p.status, "result": p.result, "decided_by": p.decided_by,
            "created_at": p.created_at.isoformat(), "decided_at": p.decided_at.isoformat() if p.decided_at else None,
            "ran_at": p.ran_at.isoformat() if p.ran_at else None}


@router.post("/ops/refresh")
async def ops_refresh(request: Request) -> RedirectResponse:
    """The Ops card's button: read everything again, back to the home."""
    watch = _watch(request)
    if watch is not None:
        await watch.refresh()
    return RedirectResponse(f"{request.app.state.base_path}/#ops", status_code=303)
