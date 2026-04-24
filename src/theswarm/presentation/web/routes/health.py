"""Health check endpoint.

When running standalone (v2 only), checks DB and SSE.
When running via the unified server, also checks GitHub and Mattermost.
Also exposes a /diagnostics/claude probe for debugging the CLI backend.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_start_time = time.time()


# Status values per check:
#   "connected" / "ok" — healthy
#   "not_configured"   — expected absence (standalone server, missing optional bot)
#   "missing"          — optional integration unavailable → warn
#   "error"            — critical failure → error
_OK_VALUES = frozenset({"ok", "connected", "not_configured"})
_WARN_VALUES = frozenset({"missing"})
_ERROR_VALUES = frozenset({"error"})


def _derive_status(checks: dict[str, str]) -> str:
    values = set(checks.values())
    if values & _ERROR_VALUES:
        return "error"
    if values & _WARN_VALUES:
        return "warn"
    if values <= _OK_VALUES:
        return "ok"
    return "error"


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    sse_hub = getattr(request.app.state, "sse_hub", None)
    project_repo = getattr(request.app.state, "project_repo", None)
    bridge = getattr(request.app.state, "gateway_bridge", None)

    checks: dict[str, str] = {}

    # DB check (critical)
    if project_repo is not None:
        try:
            await project_repo.list_all()
            checks["database"] = "connected"
        except Exception:
            checks["database"] = "error"
    else:
        checks["database"] = "not_configured"

    # SSE check
    checks["sse"] = "ok" if sse_hub is not None else "not_configured"

    # GitHub + Chat checks (only when running unified server)
    if bridge is not None:
        has_github = bool(getattr(bridge, "_swarm_po_github", None))
        has_chat = bool(getattr(bridge, "_swarm_po_chat", None))
        checks["github"] = "connected" if has_github else "missing"
        checks["chat"] = "connected" if has_chat else "missing"

    status = _derive_status(checks)

    result = {
        "status": status,
        "service": "theswarm",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "checks": checks,
    }

    if bridge is not None:
        vcs_map = getattr(bridge, "_swarm_po_vcs_map", {})
        result["repos"] = list(vcs_map.keys())

    http_status = 503 if status == "error" else 200
    return JSONResponse(result, status_code=http_status)


@router.get("/diagnostics/claude")
async def diagnostics_claude() -> JSONResponse:
    """Probe the Claude Code CLI: binary, version, auth reachability.

    Intentionally no secrets returned — path/version/stderr only, capped
    output. Lets us tell from a curl whether the CLI fallback is broken.
    """
    home = os.environ.get("HOME", "")
    binary = shutil.which("claude")
    claude_dir = os.path.join(home, ".claude") if home else ""
    claude_json = os.path.join(home, ".claude.json") if home else ""

    info: dict[str, object] = {
        "backend_mode": os.environ.get("SWARM_CLAUDE_BACKEND", "auto"),
        "binary": binary,
        "home": home,
        "claude_dir_exists": os.path.isdir(claude_dir) if claude_dir else False,
        "claude_json_exists": os.path.isfile(claude_json) if claude_json else False,
        "path": os.environ.get("PATH", "")[:500],
    }

    # Size-only snapshot of ~/.claude and ~/.claude.json so ops can see
    # whether the session is a real login or an empty stub (without
    # leaking file contents or tokens).
    if os.path.isdir(claude_dir):
        try:
            entries = []
            for name in sorted(os.listdir(claude_dir))[:30]:
                full = os.path.join(claude_dir, name)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = -1
                kind = "dir" if os.path.isdir(full) else "file"
                entries.append({"name": name, "kind": kind, "size": size})
            info["claude_dir_entries"] = entries
        except OSError as exc:
            info["claude_dir_error"] = str(exc)
    if os.path.isfile(claude_json):
        try:
            info["claude_json_size"] = os.path.getsize(claude_json)
        except OSError as exc:
            info["claude_json_error"] = str(exc)

    if binary is None:
        info["status"] = "missing"
        return JSONResponse(info, status_code=200)

    # Stat the binary — might be a symlink into npm's global prefix.
    try:
        st = os.stat(binary)
        info["binary_size"] = st.st_size
        if os.path.islink(binary):
            info["binary_target"] = os.readlink(binary)
    except OSError as exc:
        info["binary_stat_error"] = str(exc)

    # Node itself — if it hangs too, the image has a deeper problem.
    try:
        proc = await asyncio.create_subprocess_exec(
            "node", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        info["node_exit"] = proc.returncode
        info["node_stdout"] = stdout.decode(errors="replace").strip()[:100]
    except (asyncio.TimeoutError, FileNotFoundError) as exc:
        info["node_exit"] = -1
        info["node_stderr"] = str(exc)[:200]

    # `claude --version` with stdin closed + CI=1 to disable any interactive
    # prompt. ANTHROPIC_API_KEY always stripped — neither sk-ant-api keys
    # nor sk-ant-oat setup-tokens produce a working x-api-key auth, so we
    # force the CLI to use ~/.claude/.credentials.json (Bearer flow).
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env["CI"] = "1"
    env["CLAUDE_CODE_NON_INTERACTIVE"] = "1"
    info["api_key_type"] = (
        "oauth" if api_key.startswith("sk-ant-oat")
        else ("api" if api_key else "unset")
    )
    # Non-sensitive prefix only — enough to tell the token type class
    # (sk-ant-api03, sk-ant-oat01, sk-live-…) without leaking the secret.
    if api_key:
        info["api_key_prefix"] = api_key[:12]
        info["api_key_length"] = len(api_key)
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        info["version_exit"] = proc.returncode
        info["version_stdout"] = stdout.decode(errors="replace").strip()[:300]
        info["version_stderr"] = stderr.decode(errors="replace").strip()[:500]
    except asyncio.TimeoutError:
        info["version_exit"] = -1
        info["version_stdout"] = ""
        info["version_stderr"] = "timed out after 15s"

    # Full probe — -p mode with stdin closed.
    try:
        proc2 = await asyncio.create_subprocess_exec(
            binary, "-p", "reply OK", "--model", "haiku", "--output-format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=env,
        )
        stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=30)
        info["probe_exit"] = proc2.returncode
        info["probe_stdout_head"] = stdout2.decode(errors="replace").strip()[:300]
        info["probe_stderr"] = stderr2.decode(errors="replace").strip()[:500]
    except asyncio.TimeoutError:
        info["probe_exit"] = -1
        info["probe_stdout_head"] = ""
        info["probe_stderr"] = "timed out after 30s"

    info["status"] = "ok" if info.get("probe_exit") == 0 else "failing"
    return JSONResponse(info, status_code=200)
