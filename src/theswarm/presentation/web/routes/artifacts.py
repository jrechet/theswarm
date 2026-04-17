"""Serve stored demo artifacts (screenshots, videos)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

_DEFAULT_ARTIFACT_DIR = os.path.join(os.path.expanduser("~"), ".swarm-data", "artifacts")


def _artifact_base(request: Request) -> Path:
    store = getattr(request.app.state, "artifact_store", None)
    if store is not None:
        return Path(store.base_dir)
    return Path(_DEFAULT_ARTIFACT_DIR)


@router.get("/list")
async def list_artifacts(request: Request, cycle_id: str = "") -> JSONResponse:
    """List artifacts, optionally filtered by cycle."""
    base = _artifact_base(request)

    if not base.is_dir():
        return JSONResponse({"artifacts": [], "count": 0})

    artifacts = []
    search_dir = base / cycle_id if cycle_id else base

    if not search_dir.is_dir():
        return JSONResponse({"artifacts": [], "count": 0})

    for root, _dirs, files in os.walk(search_dir):
        for f in sorted(files):
            fpath = Path(root) / f
            rel = str(fpath.relative_to(base))
            artifacts.append({
                "path": rel,
                "name": f,
                "size_bytes": fpath.stat().st_size,
                "type": fpath.parent.name,
            })

    return JSONResponse({"artifacts": artifacts, "count": len(artifacts)})


@router.get("/{path:path}", response_model=None)
async def serve_artifact(request: Request, path: str) -> Response:
    """Serve an artifact file by its relative path."""
    base = _artifact_base(request)
    full_path = (base / path).resolve()

    # Prevent path traversal
    if not str(full_path).startswith(str(base.resolve())):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    if not full_path.is_file():
        return JSONResponse({"error": "Not found"}, status_code=404)

    mime_map = {
        ".png": "image/png",
        ".webm": "video/webm",
        ".diff": "text/plain",
        ".log": "text/plain",
    }
    content_type = mime_map.get(full_path.suffix, "application/octet-stream")
    return FileResponse(str(full_path), media_type=content_type)
