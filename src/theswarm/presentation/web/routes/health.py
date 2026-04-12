"""Health check endpoint.

When running standalone (v2 only), checks DB and SSE.
When running via the unified server, also checks GitHub and Mattermost.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_start_time = time.time()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    sse_hub = getattr(request.app.state, "sse_hub", None)
    project_repo = getattr(request.app.state, "project_repo", None)
    bridge = getattr(request.app.state, "gateway_bridge", None)

    checks: dict[str, str] = {}

    # DB check
    if project_repo is not None:
        try:
            await project_repo.list_all()
            checks["database"] = "connected"
        except Exception:
            checks["database"] = "error"
    else:
        checks["database"] = "not_configured"

    # SSE check
    if sse_hub is not None:
        checks["sse"] = "ok"
    else:
        checks["sse"] = "not_configured"

    # GitHub + Chat checks (only when running unified server)
    if bridge is not None:
        has_github = bool(getattr(bridge, "_swarm_po_github", None))
        has_chat = bool(getattr(bridge, "_swarm_po_chat", None))
        checks["github"] = "connected" if has_github else "missing"
        checks["chat"] = "connected" if has_chat else "missing"

    all_ok = all(v in ("ok", "connected", "not_configured")
                 for k, v in checks.items())
    status = "ok" if all_ok else "degraded"

    result = {
        "status": status,
        "service": "theswarm",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "checks": checks,
    }

    if bridge is not None:
        vcs_map = getattr(bridge, "_swarm_po_vcs_map", {})
        result["repos"] = list(vcs_map.keys())

    return JSONResponse(result)
