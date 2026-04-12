"""Health check endpoint."""

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

    checks: dict[str, str] = {}

    # DB check
    if project_repo is not None:
        try:
            await project_repo.list_all()
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
    else:
        checks["database"] = "not_configured"

    # SSE check
    if sse_hub is not None:
        checks["sse"] = "ok"
        checks["sse_clients"] = str(sse_hub.client_count)
    else:
        checks["sse"] = "not_configured"

    all_ok = all(v in ("ok", "not_configured") for v in checks.values() if not v.isdigit())
    status = "ok" if all_ok else "degraded"

    return JSONResponse({
        "status": status,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "checks": checks,
    })
