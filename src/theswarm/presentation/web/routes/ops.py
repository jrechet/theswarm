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


@router.post("/ops/refresh")
async def ops_refresh(request: Request) -> RedirectResponse:
    """The Ops card's button: read everything again, back to the home."""
    watch = _watch(request)
    if watch is not None:
        await watch.refresh()
    return RedirectResponse(f"{request.app.state.base_path}/#ops", status_code=303)
