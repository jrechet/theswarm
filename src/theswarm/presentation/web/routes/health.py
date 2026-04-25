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
from fastapi.responses import HTMLResponse, JSONResponse

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


@router.get("/health/ready", response_class=JSONResponse)
async def readiness(request: Request) -> JSONResponse:
    """Per-component readiness for triggering a cycle.

    Each component returns ok / warn / error so the dashboard can render
    a green/red list. Independent from /health which is the liveness probe.
    """
    checks: dict[str, dict] = {}

    # 1) DB
    project_repo = getattr(request.app.state, "project_repo", None)
    cycle_repo = getattr(request.app.state, "cycle_repo", None)
    if project_repo is not None:
        try:
            await project_repo.list_all()
            checks["database"] = {"status": "ok", "detail": "SQLite reachable"}
        except Exception as exc:
            checks["database"] = {"status": "error", "detail": str(exc)}
    else:
        checks["database"] = {"status": "error", "detail": "project_repo not wired"}

    # 2) Allowed repos configured
    allowed = getattr(request.app.state, "allowed_repos", []) or []
    checks["allowlist"] = (
        {"status": "ok", "detail": f"{len(allowed)} repo(s) allowed"}
        if allowed
        else {"status": "warn", "detail": "SWARM_PO_GITHUB_REPOS empty — every cycle will fail"}
    )

    # 3) GitHub bridge
    bridge = getattr(request.app.state, "gateway_bridge", None)
    has_github = bool(getattr(bridge, "_swarm_po_github", None)) if bridge else False
    checks["github"] = (
        {"status": "ok", "detail": "PyGithub client connected"}
        if has_github
        else {"status": "warn", "detail": "no GitHub client — running in stub mode"}
    )

    # 4) Claude CLI binary
    binary = shutil.which("claude")
    if binary is None:
        checks["claude_cli"] = {"status": "warn", "detail": "claude binary missing — API fallback only"}
    else:
        # Quick version probe — capped at 8 seconds.
        try:
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            env["CI"] = "1"
            env["CLAUDE_CODE_NON_INTERACTIVE"] = "1"
            proc = await asyncio.create_subprocess_exec(
                binary, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            if proc.returncode == 0:
                checks["claude_cli"] = {
                    "status": "ok",
                    "detail": stdout.decode(errors="replace").strip()[:80],
                }
            else:
                checks["claude_cli"] = {"status": "warn", "detail": f"version exit {proc.returncode}"}
        except asyncio.TimeoutError:
            checks["claude_cli"] = {"status": "error", "detail": "claude --version hung > 8s"}

    # 5) Subscription session present
    home = os.environ.get("HOME", "")
    creds = os.path.join(home, ".claude", ".credentials.json") if home else ""
    if creds and os.path.isfile(creds):
        size = os.path.getsize(creds)
        if size > 200:
            checks["claude_session"] = {"status": "ok", "detail": f".credentials.json {size} bytes"}
        else:
            checks["claude_session"] = {"status": "warn", "detail": f"file too small ({size} bytes) — re-run claude /login"}
    else:
        checks["claude_session"] = {"status": "warn", "detail": "~/.claude/.credentials.json missing"}

    # 6) Memory headroom
    try:
        import resource
        max_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux ru_maxrss is in KB; on macOS it's bytes. Assume KB.
        checks["memory"] = {"status": "ok", "detail": f"{max_rss_kb // 1024} MB peak"}
    except Exception:
        checks["memory"] = {"status": "warn", "detail": "cannot read rusage"}

    # 7) Stuck running cycles (orphans not yet reaped)
    if cycle_repo is not None:
        try:
            recent = await cycle_repo.list_recent(limit=20)
            running = [c for c in recent if str(getattr(c, "status", "")).endswith("running") or str(c.status) == "CycleStatus.RUNNING"]
            stale = []
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            cutoff = _dt.now(_tz.utc) - _td(hours=2)
            for c in running:
                if c.started_at and c.started_at < cutoff:
                    stale.append(c)
            checks["cycles"] = (
                {"status": "ok", "detail": f"{len(running)} running, none stale"}
                if not stale
                else {"status": "warn", "detail": f"{len(stale)} stale running cycle(s); reaper will clean on next boot"}
            )
        except Exception as exc:
            checks["cycles"] = {"status": "warn", "detail": f"could not read cycles: {exc}"}

    # Roll up
    statuses = {c["status"] for c in checks.values()}
    overall = "error" if "error" in statuses else ("warn" if "warn" in statuses else "ok")

    return JSONResponse({
        "status": overall,
        "checks": checks,
        "uptime_seconds": round(time.time() - _start_time, 1),
    })


@router.get("/health/ready/page", response_class=HTMLResponse)
async def readiness_page(request: Request) -> HTMLResponse:
    """Human-readable readiness page rendered with the standard sidebar shell."""
    payload = await readiness(request)
    import json as _json

    data = _json.loads(payload.body.decode())
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "health_ready.html",
        {"request": request, "data": data},
    )


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
