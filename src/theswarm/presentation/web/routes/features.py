"""Feature demo routes — browse and play recorded Playwright demos for each feature."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/features", tags=["features"])

_DEFAULT_ARTIFACT_DIR = os.path.join(os.path.expanduser("~"), ".swarm-data", "artifacts")
_DEMO_SUBDIR = "feature-demos"


def _demo_dir(request: Request) -> Path:
    store = getattr(request.app.state, "artifact_store", None)
    if store is not None:
        return Path(store.base_dir) / _DEMO_SUBDIR
    return Path(_DEFAULT_ARTIFACT_DIR) / _DEMO_SUBDIR


def _scan_videos(demo_dir: Path) -> dict[str, str]:
    """Scan demo dir for .webm files, return {feature_id: relative_path}."""
    videos: dict[str, str] = {}
    if not demo_dir.is_dir():
        return videos
    for f in sorted(demo_dir.iterdir()):
        if f.suffix == ".webm" and f.is_file():
            # File names like "hashline.webm" or "ralph_loop.webm"
            feature_id = f.stem
            videos[feature_id] = f"{_DEMO_SUBDIR}/{f.name}"
    return videos


# Feature metadata (mirrors api.py:_FEATURES)
_FEATURES = [
    {"id": "hashline", "name": "Hashline Edit Tool", "phase": 1,
     "description": "Hash-anchored file editing that prevents stale-line errors"},
    {"id": "ralph_loop", "name": "Ralph Loop", "phase": 1,
     "description": "Persistent retry loop when quality gates fail"},
    {"id": "watchdog", "name": "Todo Enforcer Watchdog", "phase": 1,
     "description": "Idle agent detection with configurable threshold and escalation"},
    {"id": "condenser", "name": "Context Condensation", "phase": 2,
     "description": "LLM-powered context summarization using Haiku"},
    {"id": "agents_md", "name": "AGENTS.md Generator", "phase": 2,
     "description": "Auto-generates documentation by introspecting agent graphs"},
    {"id": "mcp_skills", "name": "Skill-Embedded MCPs", "phase": 2,
     "description": "Mount/unmount skill manifests per task category"},
    {"id": "model_routing", "name": "Model Routing Table", "phase": 2,
     "description": "Task category to model mapping (Haiku for cheap, Sonnet for code)"},
    {"id": "intent_gate", "name": "IntentGate Enhancement", "phase": 2,
     "description": "Haiku-powered NLU with param extraction and keyword fast path"},
    {"id": "sandbox", "name": "Sandbox Protocol", "phase": 3,
     "description": "Pluggable execution backend (local, Docker, OpenHands)"},
    {"id": "ast_grep", "name": "AST-Grep Tool", "phase": 3,
     "description": "Structural code search via ast-grep CLI wrapper"},
]


@router.get("/")
async def features_page(request: Request) -> HTMLResponse:
    """Browse all 10 features with their recorded demo videos."""
    templates = request.app.state.templates
    demo_dir = _demo_dir(request)
    videos = _scan_videos(demo_dir)

    features_with_videos = []
    for feat in _FEATURES:
        features_with_videos.append({
            **feat,
            "video_path": videos.get(feat["id"]),
            "has_video": feat["id"] in videos,
        })

    phases = {1: [], 2: [], 3: []}
    for f in features_with_videos:
        phases[f["phase"]].append(f)

    return templates.TemplateResponse(
        "features.html",
        {
            "request": request,
            "phases": phases,
            "total_features": len(_FEATURES),
            "total_videos": len(videos),
        },
    )
