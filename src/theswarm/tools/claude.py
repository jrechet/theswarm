"""Claude wrapper for SWARM — prefers Claude Code CLI, falls back to Anthropic API.

Rationale: the CLI authenticates via the user's Claude Code subscription (OAuth
session in ``~/.claude/``), so prompts run against the Pro/Max quota instead of
the separately-metered API credit balance. The API path remains as a fallback
for environments where the CLI is unavailable (binary missing, no session),
and can be forced via ``SWARM_CLAUDE_BACKEND=api``.

Set ``SWARM_CLAUDE_BACKEND``:
  - ``auto`` (default): try CLI first, fall back to API on any CLI failure.
  - ``cli``: CLI only — CLI failures propagate.
  - ``api``: API only — skip CLI entirely.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import anthropic

from theswarm.infrastructure import tracing

log = logging.getLogger(__name__)

# Retryable Anthropic API errors: back off and try again.
_RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    asyncio.TimeoutError,
)

# BadRequestError substrings that indicate an account-level problem (not a
# malformed prompt): every subsequent call in the cycle will fail the same way.
_FATAL_BAD_REQUEST_MARKERS = ("credit balance", "billing", "plans & billing")

# The CLI reports an exhausted subscription window as a plain exit-1 message.
# It is a wall with a clock on it, not a hiccup: retrying cannot help until
# the stated reset. Prod cycle 980dc1e098bc burned its last two Dev
# iterations and the whole QA phase against it in 30 seconds, then reported
# a generic "CLI failed twice" that said nothing about quota.
_QUOTA_MARKERS = ("session limit", "usage limit", "quota exceeded")


def _quota_exhausted(error: Exception) -> str | None:
    """Return the CLI's own wording (which carries the reset time), else None."""
    message = str(error)
    lowered = message.lower()
    if any(marker in lowered for marker in _QUOTA_MARKERS):
        return message
    return None


class SDKTimeoutError(RuntimeError):
    """The SDK ran out of time twice, the second time resumed with more room.

    `auto` does not fall back to the CLI on it: the CLI would start the same
    work from scratch and spend the same budget again inside one phase.
    """


class ClaudeFatalError(Exception):
    """Non-retryable Claude failure: billing, auth, or invalid credentials.

    The same error would recur on every call, so the cycle should abort
    immediately instead of retrying through remaining phases/iterations.
    """


def _classify_fatal(exc: BaseException) -> str | None:
    """Return a human-readable reason if exc is account-fatal, else None."""
    if isinstance(exc, anthropic.AuthenticationError):
        return f"Anthropic authentication failed: {exc}"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return f"Anthropic permission denied: {exc}"
    if isinstance(exc, anthropic.BadRequestError):
        msg = str(exc).lower()
        if any(marker in msg for marker in _FATAL_BAD_REQUEST_MARKERS):
            return f"Anthropic account/billing error: {exc}"
    return None

# Map short names to model IDs (aliases, no date suffix — kept current).
# Prod cycle 129d471406b1: the CLI 404'd on the retired claude-sonnet-4-*
# date-pinned ID, silently falling back to the API path.
_MODEL_MAP: dict[str, str] = {
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
    "haiku": "claude-haiku-4-5",
}


@dataclass
class ClaudeResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    backend: str = ""  # "cli", "api" or "sdk"
    session_id: str = ""  # SDK only: the Claude Code session, resumable
    num_turns: int = 0  # SDK only: assistant turns taken
    # SDK only: the validated answer when the call asked for a schema
    # (``run(output_schema=...)``); None on the text backends.
    structured: dict | None = None


# Approximate pricing per 1M tokens (USD) — used for the API path.
_INPUT_COST: dict[str, float] = {
    "claude-sonnet-5": 3.0,
    "claude-opus-5": 5.0,
    "claude-haiku-4-5": 1.0,
}
_OUTPUT_COST: dict[str, float] = {
    "claude-sonnet-5": 15.0,
    "claude-opus-5": 25.0,
    "claude-haiku-4-5": 5.0,
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp = _INPUT_COST.get(model, 3.0) * input_tokens / 1_000_000
    out = _OUTPUT_COST.get(model, 15.0) * output_tokens / 1_000_000
    return inp + out


def _is_timeout(error: Exception) -> bool:
    return "timed out after" in str(error).lower()


_AUTH_FAILURE_MARKERS = (
    "oauth", "authenticate", "401", "not logged in", "invalid api key",
)


def _is_auth_failure(error: BaseException) -> bool:
    """True when a CLI failure looks like bad credentials rather than a hiccup."""
    text = str(error).lower()
    return any(marker in text for marker in _AUTH_FAILURE_MARKERS)


def _envelope_error(stdout: bytes) -> str:
    """Pull the CLI's error message out of its JSON envelope on stdout."""
    try:
        envelope = json.loads(stdout.decode(errors="replace").strip())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if not isinstance(envelope, dict):
        return ""
    message = envelope.get("result") or envelope.get("api_error_status")
    return str(message)[:300] if message else ""


class _CLIUnavailable(Exception):
    """Raised when the Claude Code CLI can't service a request.

    Signals the fallback-to-API path in auto mode. The message describes the
    specific failure (binary missing, non-zero exit, bad JSON, etc.).
    """


def _resolve_backend_mode() -> str:
    raw = os.environ.get("SWARM_CLAUDE_BACKEND", "auto").strip().lower()
    if raw in ("cli", "api", "auto", "sdk"):
        return raw
    return "auto"


def _api_backend_viable() -> bool:
    """True when ANTHROPIC_API_KEY can actually authenticate the Messages API.

    ``sk-ant-oat`` tokens come from ``claude setup-token`` and are only
    accepted through the CLI's ``Authorization: Bearer`` flow — the API's
    ``x-api-key`` header rejects them with 401. Falling back to the API while
    holding one turns any transient CLI failure into a fatal auth error
    (prod cycle 65ab4b0fdf3e), so check before falling back.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return bool(key) and not key.startswith("sk-ant-oat")


# The learned floor also outlives the ClaudeCLI instance, per workspace. A
# cycle's instance learned 420 → 546 → 709 on TheSwarm's own repo and took
# it to the grave; the next cycle paid the same sixteen minutes to learn it
# again (#99). Keyed by workdir: what needs the room is the repository.
_REPO_FLOORS: dict[str, int] = {}

# …and the process itself is replaced on every deploy, which on this
# repository is once per cycle: each self-cycle started at the constant
# again, timed out, and paid seven minutes and a dead call to relearn the
# same number (#133, cycle b209a76055a6 did it twice and then hit the
# subscription's session limit). A store, set once at startup, carries the
# floors across. `_effective_timeout` is synchronous and on the hot path,
# so reads come from the dict — primed at boot — and writes are fired off
# in the background, never awaited by the call that learned the floor.
_FLOOR_STORE: object | None = None
_FLOOR_WRITES: set[asyncio.Task] = set()


def set_floor_store(store: object | None) -> None:
    """Install (or clear) the store that outlives this process."""
    global _FLOOR_STORE
    _FLOOR_STORE = store


async def prime_repo_floors(store: object) -> None:
    """Load the learned floors at startup and keep the store for writes."""
    set_floor_store(store)
    try:
        floors = await store.load_all()
    except Exception as exc:  # a missing table, a locked DB: not worth a boot failure
        log.warning("Could not load learned CLI timeout floors: %s", exc)
        return
    for workdir, floor in floors.items():
        _REPO_FLOORS[workdir] = max(_REPO_FLOORS.get(workdir, 0), int(floor))
    if floors:
        log.info("Loaded %d learned CLI timeout floor(s)", len(floors))


def _remember_floor(workdir: str, floor: int) -> None:
    """Raise the in-process floor and, best effort, the stored one."""
    _REPO_FLOORS[workdir] = max(_REPO_FLOORS.get(workdir, 0), floor)
    store = _FLOOR_STORE
    if store is None:
        return

    async def _write() -> None:
        try:
            await store.save(workdir, floor)
        except Exception as exc:
            log.warning("Could not persist the CLI timeout floor for %s: %s", workdir, exc)

    try:
        task = asyncio.get_running_loop().create_task(_write())
    except RuntimeError:
        return  # no loop (a sync test): the in-process floor still holds
    _FLOOR_WRITES.add(task)
    task.add_done_callback(_FLOOR_WRITES.discard)


async def drain_floor_writes() -> None:
    """Await the pending floor writes — for tests and a clean shutdown."""
    while _FLOOR_WRITES:
        await asyncio.gather(*tuple(_FLOOR_WRITES), return_exceptions=True)


# The target's own venv inside its workspace (agents/base.TARGET_VENV_DIR;
# not imported: agents import this module).
TARGET_VENV_DIR = ".venv-swarm"


def _own_venv() -> str:
    """TheSwarm's own venv (sys.prefix), "" when it runs on a bare interpreter."""
    return sys.prefix if sys.prefix != sys.base_prefix else ""


def _python_for_target(env: dict[str, str], workdir: str | None) -> None:
    """Point `python`, `pip` and `uv pip` of a Claude child at the target.

    The container's PATH starts with TheSwarm's venv, so a Dev that ran the
    target's tests through Bash reached for it: cycle 83b584194589 ran `uv
    pip install -r requirements.txt --python /app/.venv/bin/python` and
    replaced TheSwarm's fastapi, pydantic and uvicorn with the target's pins
    under the running server. TheSwarm's venv leaves PATH; the workspace's
    `.venv-swarm` goes first when it exists, and VIRTUAL_ENV names it (or
    nothing — an explicit "" because the SDK merges env over os.environ).
    """
    own = _own_venv()
    own_bin = os.path.realpath(os.path.join(own, "bin")) if own else ""
    parts = [
        p for p in env.get("PATH", "").split(os.pathsep)
        if p and (not own_bin or os.path.realpath(p) != own_bin)
    ]
    env["VIRTUAL_ENV"] = ""
    if workdir:
        venv = os.path.join(workdir, TARGET_VENV_DIR)
        if os.path.isdir(os.path.join(venv, "bin")):
            parts.insert(0, os.path.join(venv, "bin"))
            env["VIRTUAL_ENV"] = venv
    env["PATH"] = os.pathsep.join(parts)


def _child_env(*, drop_oauth_env: bool = False, workdir: str | None = None) -> dict[str, str]:
    """The environment a Claude Code process gets — CLI subprocess or SDK.

    Closes off interactive prompts (CI=1: update banner, login nag, telemetry
    opt-in) and strips ANTHROPIC_API_KEY, always:

    - an sk-ant-api key defeats the point of the subscription backends, and
      in the binary's credential precedence it sits *above* the OAuth token
      and the session on disk, so leaving it in silently moves the cycle to
      per-token billing (V2 runtime invariant I1);
    - an sk-ant-oat token from `claude setup-token` looks API-shaped but the
      x-api-key header rejects it ('Invalid API key · Fix external API key');
      it is only accepted on the Authorization: Bearer flow the binary uses
      for CLAUDE_CODE_OAUTH_TOKEN and ~/.claude/.credentials.json.

    ``drop_oauth_env`` removes CLAUDE_CODE_OAUTH_TOKEN too: it wins over the
    session on disk, so a stale one breaks every call even while ~/.claude
    holds valid, self-refreshing credentials. The caller retries without it.
    """
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env["CI"] = "1"
    env["CLAUDE_CODE_NON_INTERACTIVE"] = "1"
    # No auto-memory (I2): earlier runs in this home left memory files under
    # ~/.claude/projects/<workspace>/memory, and the binary loads their index
    # into every call — cycle 71c8b870041a's PO tried to Read them.
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    _python_for_target(env, workdir)
    if drop_oauth_env:
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    return env


def _sdk_child_env(*, drop_oauth_env: bool = False, workdir: str | None = None) -> dict[str, str]:
    """``_child_env`` for ``ClaudeAgentOptions.env`` — which is *merged over*
    the parent's full ``os.environ`` by the SDK's transport, not used in its
    place like ``create_subprocess_exec(env=...)``. Omitting a key does not
    remove it there: measured on 2026-09-23, an omitted ANTHROPIC_API_KEY
    came back as ``apiKeySource: ANTHROPIC_API_KEY``, an empty override as
    ``none`` (the subscription). So the keys I1 forbids are overridden to
    empty, explicitly. The OAuth override is still *dropped* (its absence
    is what lets the session on disk win); an empty override there would
    shadow that session.
    """
    env = _child_env(drop_oauth_env=drop_oauth_env, workdir=workdir)
    env["ANTHROPIC_API_KEY"] = ""
    return env


# ── Agent SDK (V2 runtime; M0 ships the probe, M1 the backend) ──────────
#
# The SDK runs the same Claude Code binary as `claude -p`, bundled in its
# wheel, and authenticates the same way: CLAUDE_CODE_OAUTH_TOKEN, else the
# session in ~/.claude. What it adds is a stream of typed messages instead
# of one JSON envelope — the class of bugs where the verdict was "whatever
# Claude said last" (#125, the host Stop hook) has no transport to ride on.

_SDK_PROBE_PROMPT = "Reply with exactly the single word: OK"
_SDK_PROBE_TIMEOUT_SECONDS = 90


def _sdk_query(prompt: str, options: object):
    """``claude_agent_sdk.query`` behind one seam, so tests replace it."""
    from claude_agent_sdk import query

    return query(prompt=prompt, options=options)


def sdk_binary_location() -> str:
    """Where the SDK's Claude Code binary comes from, for the validate report.

    ``bundled:<path>`` when the platform wheel ships it (linux x86_64 and
    macOS do), ``path:<path>`` when only a `claude` on PATH exists, "" when
    neither — the SDK would raise CLINotFoundError.
    """
    try:
        import claude_agent_sdk
    except ImportError:
        return ""
    bundled = os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled", "claude")
    if os.path.isfile(bundled):
        return f"bundled:{bundled}"
    on_path = shutil.which("claude")
    return f"path:{on_path}" if on_path else ""


def _identity_from_api_key_source(source: object) -> str:
    """Read the binary's ``apiKeySource`` (init message) as an identity.

    ``none`` is the OAuth path — the subscription, via the env token or the
    session file. Anything naming a key or a helper is per-token billing.
    """
    if source is None:
        return "unknown"
    lowered = str(source).strip().lower()
    if lowered == "none":
        return "subscription"
    if "api_key" in lowered or "apikey" in lowered or "helper" in lowered:
        return "api-key"
    return lowered


async def probe_sdk(
    *, model: str = "haiku", timeout: float = _SDK_PROBE_TIMEOUT_SECONDS,
) -> dict:
    """One-turn call through the SDK, reporting who answered and at what cost.

    Never raises: the report carries ``ok`` and ``error``. ``ok`` is False
    when the call failed, produced no result, or — the case this probe
    exists for — answered with an API key instead of the subscription.
    """
    report: dict = {
        "ok": False,
        "identity": "unknown",
        "model": _MODEL_MAP.get(model, model),
        "session_id": "",
        "cost_usd": 0.0,
        "claude_code_version": "",
        "binary": sdk_binary_location(),
        "error": "",
    }
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, SystemMessage

        options = ClaudeAgentOptions(
            model=report["model"],
            env=_sdk_child_env(),
            # No host settings, hooks or CLAUDE.md: what the swarm runs is
            # decided in this codebase (invariant I2).
            setting_sources=[],
            allowed_tools=[],
            max_turns=1,
            permission_mode="default",
        )
    except Exception as exc:  # noqa: BLE001 — a missing or changed SDK is a report, not a crash
        report["error"] = f"claude-agent-sdk unavailable: {type(exc).__name__}: {exc}"
        return report

    async def _consume() -> None:
        async for message in _sdk_query(_SDK_PROBE_PROMPT, options):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                data = message.data or {}
                report["identity"] = _identity_from_api_key_source(data.get("apiKeySource"))
                report["claude_code_version"] = str(data.get("claude_code_version", ""))
                report["session_id"] = str(data.get("session_id", ""))
            elif isinstance(message, ResultMessage):
                report["session_id"] = message.session_id or report["session_id"]
                report["cost_usd"] = float(message.total_cost_usd or 0.0)
                if message.is_error or message.subtype != "success":
                    report["error"] = f"{message.subtype}: {message.result or 'no detail'}"
                    return
                report["ok"] = True

    try:
        await asyncio.wait_for(_consume(), timeout=timeout)
    except asyncio.TimeoutError:
        report["ok"] = False
        report["error"] = f"probe timed out after {timeout}s"
        return report
    except Exception as exc:  # noqa: BLE001 — a probe reports, it never raises
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    if report["identity"] == "api-key":
        report["ok"] = False
        report["error"] = (
            "the SDK answered with ANTHROPIC_API_KEY — the child env must not "
            "carry it (V2 runtime invariant I1)"
        )
    elif report["ok"] and report["identity"] != "subscription":
        # The probe exists to *confirm* the subscription answered; an init
        # message without the field, or with a value this code does not
        # know, is not a confirmation.
        report["ok"] = False
        report["error"] = (
            f"the SDK did not confirm the subscription identity "
            f"(apiKeySource read as {report['identity']!r})"
        )
    elif not report["ok"] and not report["error"]:
        report["error"] = "no result message from the SDK"
    return report


# ── Agent SDK backend (M1) ────────────────────────────────────────────
#
# One call, one profile. The profile is read off the call itself — the
# same two arguments the CLI path always took — so no caller changes:
#   edit  acceptEdits + workdir   the Dev implements and repairs
#   read  workdir, no edit mode   QA writes E2E tests, the PO reads context
#   text  no workdir              review, breakdown, plan, memory, feedback
# What each profile may touch is decided here, in code, and tested —
# never by a settings.json mounted from the host (invariant I2).

SDK_CONTINUE_PROMPT = (
    "Continue where you left off. The working tree already contains your "
    "edits; do not start over. Finish the task and stop."
)

# Tools auto-approved per profile. Bash is deliberately absent from every
# list: an auto-approved tool never reaches `can_use_tool`, and Bash is the
# one that needs a look at its argument (pushes, gh, secrets).
_SDK_ALLOWED_TOOLS: dict[str, list[str]] = {
    "edit": ["Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Glob", "Grep", "TodoWrite"],
    "read": ["Read", "Glob", "Grep"],
    "text": [],
}
# What `decide_tool_use` may say yes to — the allowlist above plus Bash
# for the Dev, judged call by call.
_SDK_PROFILE_TOOLS: dict[str, frozenset[str]] = {
    "edit": frozenset(_SDK_ALLOWED_TOOLS["edit"]) | {"Bash"},
    "read": frozenset(_SDK_ALLOWED_TOOLS["read"]),
    "text": frozenset(),
}
# The SDK's own mechanics, allowed in every profile: with `output_format`
# the answer itself is delivered as a call to "StructuredOutput". Refusing
# it refuses the answer — the first prod breakdown on M3 (cycle
# 71c8b870041a) was refused three times and failed "no structured output".
_SDK_MECHANICS_TOOLS = frozenset({"StructuredOutput"})
# Never, in any profile: the web is not the workspace, and a sub-agent is a
# budget nobody accounted for.
_SDK_DISALLOWED_TOOLS = ["WebSearch", "WebFetch", "Task"]
# A ceiling on assistant turns so a call cannot loop until the phase
# timeout; the external timeout stays the real budget.
_SDK_MAX_TURNS: dict[str, int] = {"edit": 200, "read": 40, "text": 8}
_SDK_FILE_TOOLS = ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit")
_SDK_PATH_TOOLS = _SDK_FILE_TOOLS + ("Glob", "Grep")
_SDK_BASH_DENY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgit\s+push\b"), "the pipeline pushes; the Dev only commits"),
    (re.compile(r"(^|[\s;&|(])gh(\s|$)"), "gh is the pipeline's tool, not the Dev's"),
    (re.compile(r"(^|[\s/'\"])\.env(\.[\w.-]+)?\b"), ".env files hold secrets"),
    (re.compile(r"\bgit\s+config\b"), "git config is owned by the pipeline"),
    (re.compile(r"\bgit\s+remote\s+(set-url|add)\b"), "remotes are owned by the pipeline"),
)


class _SDKTimeout(_CLIUnavailable):
    """An SDK call ran out of budget; ``session_id`` is what to resume."""

    def __init__(self, message: str, session_id: str = "") -> None:
        super().__init__(message)
        self.session_id = session_id


def _profile_for(workdir: str | None, permission_mode: str | None) -> str:
    if permission_mode == "acceptEdits":
        return "edit"
    return "read" if workdir else "text"


def _path_inside(raw: str, workspace: str | None) -> tuple[bool, str]:
    """Is ``raw`` a path inside the workspace, and not a secret or git state?"""
    if not workspace:
        return True, ""
    root = os.path.normpath(workspace)
    target = os.path.normpath(os.path.join(root, raw))
    if target != root and not target.startswith(root + os.sep):
        return False, f"{raw} is outside the workspace"
    parts = os.path.relpath(target, root).split(os.sep)
    if ".git" in parts:
        return False, ".git is owned by the pipeline"
    name = parts[-1]
    if name == ".env" or name.startswith(".env."):
        return False, ".env files hold secrets"
    return True, ""


def decide_tool_use(
    profile: str, workspace: str | None, tool_name: str, tool_input: dict,
) -> tuple[bool, str]:
    """The permission policy, as a pure function: (allowed, reason).

    Everything the SDK asks about comes here; what the profile auto-approves
    never does. Bash is judged on its command, file tools on their path.
    """
    if tool_name in _SDK_MECHANICS_TOOLS:
        return True, ""
    if tool_name not in _SDK_PROFILE_TOOLS.get(profile, frozenset()):
        return False, f"{tool_name} is not available to a {profile} call"
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        for pattern, why in _SDK_BASH_DENY:
            if pattern.search(command):
                return False, why
        own = _own_venv()
        if own and own in command:
            return False, (
                "that is TheSwarm's own venv, not the target's — install and "
                f"test with the workspace's {TARGET_VENV_DIR} (`python` on PATH)"
            )
        return True, ""
    if tool_name in _SDK_PATH_TOOLS:
        raw = (
            tool_input.get("file_path")
            or tool_input.get("notebook_path")
            or tool_input.get("path")
        )
        if raw:
            return _path_inside(str(raw), workspace)
    return True, ""


def _permission_hook(profile: str, workspace: str | None):
    """The policy as a PreToolUse hook — the only seat that sees every call.

    `can_use_tool` is consulted only for tools the permission system has
    not already approved: anything in `allowed_tools`, and reads inside the
    project, never reach it (the SDK warns: CanUseToolShadowedWarning).
    A hook runs before that decision, so this is where "outside the
    workspace" and ".env" are refused for Read and Edit too. It returns a
    deny with the reason, or nothing — the normal flow then decides.
    """

    async def hook(input_data, tool_use_id, context):
        tool_name = str(input_data.get("tool_name", ""))
        tool_input = dict(input_data.get("tool_input") or {})
        allowed, why = decide_tool_use(profile, workspace, tool_name, tool_input)
        if allowed:
            return {}
        log.info("Claude SDK: refused %s — %s", tool_name, why)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": why,
            }
        }

    return hook


def _relative(path: str, workspace: str | None) -> str:
    if workspace:
        root = os.path.normpath(workspace)
        target = os.path.normpath(os.path.join(root, path))
        if target.startswith(root + os.sep):
            return os.path.relpath(target, root)
    return path


# Pseudo-tools the SDK uses for its own mechanics — the structured answer is
# delivered as a "StructuredOutput" tool call — say nothing to the theater.
_SILENT_TOOLS = frozenset({"StructuredOutput"})


def _tool_event(name: str, tool_input: dict, workspace: str | None) -> str:
    """One line per tool call for the theater: what, never the contents."""
    from theswarm.tools.git import redact

    if name in _SILENT_TOOLS:
        return ""
    if name in _SDK_FILE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return f"{name} {_relative(str(raw), workspace)}".strip()
    if name == "Bash":
        command = " ".join(str(tool_input.get("command", "")).split())
        return f"Bash: {redact(command)[:120]}"
    if name in ("Glob", "Grep"):
        return f'{name} "{tool_input.get("pattern", "")}"'[:120]
    return name


_CODE_LINE_PREFIXES = (
    "import ", "from ", "def ", "class ", "async def ", "#", "```", "{", "}", "[", "<",
    "---", "@", "return ", "if ", "for ", "while ", "try:", "except", "with ",
)


def _text_event(text: str) -> str:
    """The first prose line of a text block, redacted and short.

    A block that *is* code — the QA's generated E2E file, a JSON verdict —
    said "import uuid" or "```json" to the theater (cycle e4978adebe03).
    Code-looking lines are skipped; a block with no prose says nothing.
    """
    from theswarm.tools.git import redact

    for raw in text.splitlines():
        line = raw.strip()
        # an indented line is a line of code; prose does not indent
        if not line or raw[:1].isspace() or line.startswith(_CODE_LINE_PREFIXES):
            continue
        return redact(line)[:160]
    return ""


@dataclass
class ClaudeCLI:
    """Runs a prompt through Claude Code CLI first, Anthropic API as fallback.

    The class name is kept for backward compatibility — callers import
    ``ClaudeCLI`` across the codebase.
    """
    model: str = "sonnet"
    # 3 min: a typical Dev iteration prompt finishes in <90s. Anything
    # longer is a hang; fail fast and surface it. Old default (600s × 1.5
    # × 3 retries = 47 min) made stuck cycles indistinguishable from
    # in-flight ones.
    timeout: int = 180
    max_tokens: int = 8192
    # Adaptive retry/backoff (applies to the API fallback only).
    max_retries: int = 2
    retry_base_ms: int = 1000
    timeout_growth: float = 1.3
    # Ceiling on the learned floor below. `dev_iter` budgets 30 min and must
    # still hold one call plus its retry, so 2 × 780s = 1560s leaves ~4 min
    # for the dependency install, the test run and the commit around them.
    timeout_ceiling: int = 780
    # The largest budget already proven insufficient, learned across calls.
    # Not a tuning knob: it only ever moves up, and only after a real timeout.
    _timeout_floor: int = field(default=0, repr=False)
    # SDK backend: where tool calls and text blocks go while a call runs —
    # cycle.py points it at the theater, as the running role's progress.
    on_event: Callable[[str], Awaitable[None]] | None = field(default=None, repr=False)
    # Injected so tests can stub. Not repr-ed.
    _sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, repr=False)
    _rng: random.Random = field(default_factory=random.Random, repr=False)

    def _effective_timeout(self, timeout: int | None, workdir: str | None = None) -> int:
        """The budget to actually use: never one that has already expired.

        `_retry_timeout` grows a budget *within* a single `run()`. That alone
        cannot escape a repo where the work simply needs more room than the
        caller's constant: the next dev iteration starts back at the original
        budget, dies at exactly the same point, and pays the same tuition
        again. TheSwarm asked to work on its own source did that five times
        over — 420s then 546s, 16 minutes an iteration, no progress and no
        new information (cycle be8e68aaef9d, issue #85).
        """
        return max(
            timeout or self.timeout,
            self._timeout_floor,
            _REPO_FLOORS.get(workdir or "", 0),
        )

    def _resolve_model(self) -> str:
        return _MODEL_MAP.get(self.model, self.model)

    def for_task(self, task_category: str, routing: dict[str, str] | None = None) -> ClaudeCLI:
        """Return a new ClaudeCLI configured for a specific task category."""
        if routing is None:
            return ClaudeCLI(
                model=self.model, timeout=self.timeout, max_tokens=self.max_tokens,
                max_retries=self.max_retries, retry_base_ms=self.retry_base_ms,
                timeout_growth=self.timeout_growth,
                timeout_ceiling=self.timeout_ceiling,
                on_event=self.on_event,
                _timeout_floor=self._timeout_floor,
            )
        model = routing.get(task_category, self.model)
        return ClaudeCLI(
            model=model, timeout=self.timeout, max_tokens=self.max_tokens,
            max_retries=self.max_retries, retry_base_ms=self.retry_base_ms,
            timeout_growth=self.timeout_growth,
            timeout_ceiling=self.timeout_ceiling,
            on_event=self.on_event,
            _timeout_floor=self._timeout_floor,
        )

    def _compute_backoff_ms(self, attempt: int) -> int:
        """Exponential backoff + jitter. attempt is 0-indexed."""
        base = self.retry_base_ms * (2 ** attempt)
        jitter = self._rng.randint(0, self.retry_base_ms)
        return base + jitter

    async def run(
        self,
        prompt: str,
        *,
        workdir: str | None = None,
        timeout: int | None = None,
        permission_mode: str | None = None,
        output_schema: dict | None = None,
    ) -> ClaudeResult:
        """Run a prompt. Tries CLI first, falls back to API on failure.

        ``output_schema`` (a JSON Schema, draft-07) asks the SDK backend for
        a validated answer in ``ClaudeResult.structured``; the text backends
        ignore it and the caller falls back to its text parser (M3).

        Honors ``SWARM_CLAUDE_BACKEND`` (``auto`` | ``cli`` | ``api``).

        ``permission_mode`` is the CLI's ``--permission-mode``. Print mode
        grants nothing by itself: an ``Edit`` in the workspace is refused
        and Claude falls back to describing the change — which is how a
        five-minute implementation ended as "no file changes" (#125). The
        Dev passes ``acceptEdits`` so edits inside ``workdir`` go through;
        reviews and plans pass nothing. The API backend has no tools and
        ignores it.
        """
        backend = _resolve_backend_mode()
        with tracing.span(
            "claude.call",
            **{
                "swarm.backend": backend,
                "swarm.model": self._resolve_model(),
                "swarm.profile": _profile_for(workdir, permission_mode),
                "swarm.prompt_chars": len(prompt or ""),
                "swarm.timeout_s": self._effective_timeout(timeout, workdir),
                "swarm.structured": output_schema is not None,
            },
        ) as current:
            result = await self._dispatch(
                prompt, backend, workdir=workdir, timeout=timeout,
                permission_mode=permission_mode, output_schema=output_schema,
            )
            tracing.set_attributes(
                current,
                **{
                    "swarm.backend": result.backend,
                    "swarm.input_tokens": result.input_tokens,
                    "swarm.output_tokens": result.output_tokens,
                    "swarm.cost_usd": result.cost_usd,
                    "swarm.turns": result.num_turns,
                    "swarm.session_id": result.session_id,
                },
            )
            return result

    async def _dispatch(
        self, prompt: str, backend: str, *, workdir: str | None,
        timeout: int | None, permission_mode: str | None,
        output_schema: dict | None = None,
    ) -> ClaudeResult:
        """The backend switch; ``run`` wraps it in the call's span."""
        if backend == "api":
            return await self._run_api(prompt, workdir=workdir, timeout=timeout)

        if backend == "sdk":
            return await self._sdk_with_recovery(
                prompt, workdir=workdir, timeout=timeout,
                permission_mode=permission_mode, output_schema=output_schema,
            )

        if backend == "auto":
            # sdk → cli → api (V2 runtime M1, after three consecutive green
            # harness cycles on the sdk backend). A quota is fatal on every
            # backend and a spent timeout would only be spent again; any
            # other SDK failure (not installed, a broken stream, no
            # structured answer) falls through to the CLI chain, whose text
            # the callers still parse.
            try:
                return await self._sdk_with_recovery(
                    prompt, workdir=workdir, timeout=timeout,
                    permission_mode=permission_mode, output_schema=output_schema,
                )
            except SDKTimeoutError:
                raise
            except RuntimeError as sdk_error:
                log.warning("Claude SDK failed (%s) — falling back to the CLI", sdk_error)

        try:
            return await self._cli_with_auth_recovery(
                prompt, workdir=workdir, timeout=timeout,
                permission_mode=permission_mode,
            )
        except _CLIUnavailable as exc:
            first_error = exc

        # Out of subscription window: every later call fails identically until
        # the reset the CLI names. Abort the cycle now, keeping its wording so
        # the failure says when work can resume.
        quota = _quota_exhausted(first_error)
        if quota is not None:
            raise ClaudeFatalError(f"Claude subscription exhausted: {quota}")

        if backend == "cli":
            raise RuntimeError(
                f"Claude CLI unavailable (forced): {first_error}"
            ) from first_error

        # Auto mode. Falling back to the API only helps when the API can
        # authenticate; with an OAuth session token it always 401s, so a
        # transient CLI hiccup would become a fatal cycle error. Retry the
        # CLI once instead and surface its real failure.
        if not _api_backend_viable():
            log.warning(
                "Claude CLI failed (%s) and the API fallback cannot authenticate "
                "(no usable ANTHROPIC_API_KEY) — retrying the CLI once",
                first_error,
            )
            try:
                return await self._cli_with_auth_recovery(
                    prompt, workdir=workdir,
                    timeout=self._retry_timeout(timeout, first_error, workdir=workdir),
                    permission_mode=permission_mode,
                )
            except _CLIUnavailable as retry_error:
                raise RuntimeError(
                    "Claude CLI failed twice and no usable API credential is "
                    f"available (ANTHROPIC_API_KEY is unset or an OAuth token): "
                    f"{retry_error}"
                ) from retry_error

        log.warning("Claude CLI unavailable (%s) — falling back to API", first_error)
        return await self._run_api(prompt, workdir=workdir, timeout=timeout)

    # ── SDK backend ──────────────────────────────────────────────────

    async def _emit(self, message: str) -> None:
        """Hand an event to the theater; a broken bridge never fails a call."""
        if self.on_event is None or not message:
            return
        try:
            await self.on_event(message)
        except Exception as exc:  # noqa: BLE001 — reporting is best effort
            log.debug("on_event failed (%s) — continuing", exc)

    def _sdk_options(
        self, profile: str, workdir: str | None, model_id: str,
        *, drop_oauth_env: bool, resume: str | None,
        output_schema: dict | None = None,
    ):
        from claude_agent_sdk import (
            ClaudeAgentOptions,
            HookMatcher,
            PermissionResultAllow,
            PermissionResultDeny,
        )

        # Two seats, one policy. The hook sees every call and refuses first;
        # the callback answers the permission requests that remain (Bash,
        # which no list auto-approves).
        async def can_use_tool(tool_name, tool_input, context):
            allowed, why = decide_tool_use(profile, workdir, tool_name, dict(tool_input or {}))
            if allowed:
                return PermissionResultAllow()
            log.info("Claude SDK: refused %s — %s", tool_name, why)
            return PermissionResultDeny(message=why)

        return ClaudeAgentOptions(
            model=model_id,
            cwd=workdir,
            env=_sdk_child_env(drop_oauth_env=drop_oauth_env, workdir=workdir),
            # Nothing from the host — no settings.json, no hooks, no
            # CLAUDE.md of the user (I2). The target's own guidance reaches
            # the model through the prompt's context, as it always has.
            setting_sources=[],
            # Claude Code's own system prompt where tools are in play; a
            # bare prompt for the text calls, whose prompts are complete.
            system_prompt=(
                {"type": "preset", "preset": "claude_code"} if profile != "text" else None
            ),
            permission_mode="acceptEdits" if profile == "edit" else "default",
            # What the model sees is what the policy allows: a tool it cannot
            # use is a turn spent asking for it. The first breakdown after the
            # StructuredOutput fix asked for Bash twice and AskUserQuestion
            # once before answering; with the base set narrowed, a text call
            # answers in two turns for a seventh of the price (measured on
            # prod 2026-09-23). StructuredOutput is not a base tool and
            # survives an empty set.
            tools=sorted(_SDK_PROFILE_TOOLS[profile]),
            allowed_tools=list(_SDK_ALLOWED_TOOLS[profile]),
            disallowed_tools=list(_SDK_DISALLOWED_TOOLS),
            can_use_tool=can_use_tool,
            hooks={"PreToolUse": [HookMatcher(hooks=[_permission_hook(profile, workdir)])]},
            max_turns=_SDK_MAX_TURNS[profile],
            resume=resume,
            output_format=(
                {"type": "json_schema", "schema": output_schema} if output_schema else None
            ),
        )

    async def _run_sdk(
        self,
        prompt: str,
        *,
        workdir: str | None,
        timeout: int | None,
        permission_mode: str | None,
        drop_oauth_env: bool = False,
        resume: str | None = None,
        output_schema: dict | None = None,
    ) -> ClaudeResult:
        """One call through the Agent SDK: stream the messages, keep the result.

        Fails via ``_CLIUnavailable`` (``_SDKTimeout`` on budget, with the
        session to resume) so ``_sdk_with_recovery`` can decide.
        """
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ResultMessage,
                SystemMessage,
                TextBlock,
                ToolUseBlock,
            )
        except ImportError as exc:
            raise _CLIUnavailable(f"claude-agent-sdk not installed: {exc}") from exc

        effective_timeout = self._effective_timeout(timeout, workdir)
        model_id = self._resolve_model()
        profile = _profile_for(workdir, permission_mode)
        options = self._sdk_options(
            profile, workdir, model_id, drop_oauth_env=drop_oauth_env, resume=resume,
            output_schema=output_schema,
        )
        log.info(
            "Claude SDK: model=%s profile=%s workdir=%s timeout=%ds prompt_chars=%d resume=%s",
            model_id, profile, workdir, effective_timeout, len(prompt or ""), resume or "-",
        )

        seen: dict = {"session_id": resume or "", "result": None}

        async def _consume() -> None:
            async for message in _sdk_query(prompt, options):
                if isinstance(message, SystemMessage):
                    if message.subtype == "init":
                        data = message.data or {}
                        seen["session_id"] = str(data.get("session_id") or seen["session_id"])
                        # I1, on every call, not only in the probe: the binary
                        # says who it is before it works; a key is a stop.
                        identity = _identity_from_api_key_source(data.get("apiKeySource"))
                        if identity == "api-key":
                            raise _CLIUnavailable(
                                "the SDK answered with ANTHROPIC_API_KEY — refusing to "
                                "run a cycle on per-token billing (V2 runtime invariant I1)"
                            )
                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            await self._emit(_text_event(block.text))
                        elif isinstance(block, ToolUseBlock):
                            await self._emit(_tool_event(block.name, dict(block.input or {}), workdir))
                elif isinstance(message, ResultMessage):
                    seen["result"] = message

        try:
            await asyncio.wait_for(_consume(), timeout=effective_timeout)
        except asyncio.TimeoutError as exc:
            # Cancelling the consumer closes the SDK's generator, whose
            # `finally` terminates the subprocess (claude_agent_sdk/_internal/client.py).
            raise _SDKTimeout(
                f"SDK timed out after {effective_timeout}s", session_id=seen["session_id"],
            ) from exc
        except _CLIUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — the SDK's own errors, mapped
            result = seen["result"]
            if result is not None and result.is_error:
                raise _CLIUnavailable(
                    f"SDK result {result.subtype}: {result.result or exc}"
                ) from exc
            raise _CLIUnavailable(f"{type(exc).__name__}: {exc}") from exc

        result = seen["result"]
        if result is None:
            raise _CLIUnavailable("SDK stream ended without a result message")
        if result.is_error or result.subtype != "success":
            raise _CLIUnavailable(f"SDK result {result.subtype}: {result.result or 'no detail'}")
        structured = result.structured_output
        if output_schema is not None and not isinstance(structured, dict):
            # A schema was asked for and nothing validated came back: the
            # docs call this a failure too ("success" with no structured
            # output). Never guess from the text.
            raise _CLIUnavailable(
                "SDK result success but no structured output for the requested schema"
            )

        usage = result.usage or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        cost_usd = float(result.total_cost_usd or 0.0)
        log.info(
            "Claude SDK result: $%.4f  model=%s  in=%d out=%d turns=%d session=%s",
            cost_usd, model_id, input_tokens, output_tokens, result.num_turns,
            result.session_id,
        )
        return ClaudeResult(
            text=result.result or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            model=model_id,
            backend="sdk",
            session_id=result.session_id or seen["session_id"],
            num_turns=int(result.num_turns or 0),
            structured=structured if isinstance(structured, dict) else None,
        )

    async def _sdk_with_recovery(
        self, prompt: str, *, workdir: str | None, timeout: int | None,
        permission_mode: str | None, output_schema: dict | None = None,
    ) -> ClaudeResult:
        """Run through the SDK with the three recoveries the CLI path learned.

        A timeout is *resumed* — the session keeps its context and the tree
        keeps its edits — with more room (`_retry_timeout`). An auth failure
        with the env override present is retried once without it, and the
        original failure is what surfaces if that probe fails too. An
        exhausted subscription window is fatal. Anything else is a failed
        call: the caller skips the step (invariant I6), never the CLI or
        the API — forced means forced.
        """
        try:
            return await self._run_sdk(
                prompt, workdir=workdir, timeout=timeout, permission_mode=permission_mode,
                output_schema=output_schema,
            )
        except _CLIUnavailable as exc:
            first = exc

        quota = _quota_exhausted(first)
        if quota is not None:
            raise ClaudeFatalError(f"Claude subscription exhausted: {quota}")

        if isinstance(first, _SDKTimeout):
            grown = self._retry_timeout(timeout, first, workdir=workdir)
            resume = first.session_id or None
            log.warning(
                "Claude SDK timed out — %s with %ds",
                f"resuming session {resume}" if resume else "re-prompting", grown,
            )
            try:
                return await self._run_sdk(
                    SDK_CONTINUE_PROMPT if resume else prompt,
                    workdir=workdir, timeout=grown, permission_mode=permission_mode,
                    resume=resume, output_schema=output_schema,
                )
            except _CLIUnavailable as again:
                quota = _quota_exhausted(again)
                if quota is not None:
                    raise ClaudeFatalError(f"Claude subscription exhausted: {quota}")
                raise SDKTimeoutError(f"Claude SDK failed twice: {again}") from again

        if _is_auth_failure(first) and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            log.warning(
                "Claude SDK failed (%s) — retrying without the CLAUDE_CODE_OAUTH_TOKEN "
                "env override", first,
            )
            try:
                return await self._run_sdk(
                    prompt, workdir=workdir, timeout=timeout,
                    permission_mode=permission_mode, drop_oauth_env=True,
                    output_schema=output_schema,
                )
            except _CLIUnavailable as without_token:
                log.warning(
                    "Claude SDK also failed without the env token (%s) — keeping the "
                    "original failure", without_token,
                )
                raise RuntimeError(f"Claude SDK failed: {first}") from without_token

        raise RuntimeError(f"Claude SDK failed: {first}") from first

    async def _cli_with_auth_recovery(
        self, prompt: str, *, workdir: str | None, timeout: int | None,
        permission_mode: str | None = None,
    ) -> ClaudeResult:
        """Run the CLI, recovering from a stale env token on any attempt.

        A stale CLAUDE_CODE_OAUTH_TOKEN outranks the session on disk, so it
        breaks every call while ~/.claude still holds valid, self-refreshing
        credentials — which took prod down twice. The recovery used to guard
        only the first attempt, so an auth error surfacing on the *retry* went
        unhandled: prod cycle c3ab6da6f5d9 timed out, earned its grown retry,
        and that retry died on an expired token with no second chance.
        """
        try:
            return await self._run_cli(
                prompt, workdir=workdir, timeout=timeout,
                permission_mode=permission_mode,
            )
        except _CLIUnavailable as exc:
            # A stale env token does not always fail loudly. In prod it made
            # the CLI *hang*: `claude -p` returned rc=124 after 90s with the
            # token set and rc=0 instantly without it. Recovery keyed only on
            # auth *errors* never fired, so every call burned its full
            # timeout, retried, hung again, and the cycle died slowly. Treat
            # a timeout as a candidate too whenever the override is present.
            if not ((_is_auth_failure(exc) or _is_timeout(exc))
                    and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
                raise
            log.warning(
                "Claude CLI failed (%s) — retrying without the "
                "CLAUDE_CODE_OAUTH_TOKEN env override", exc,
            )
            try:
                return await self._run_cli(
                    prompt, workdir=workdir, timeout=timeout,
                    drop_oauth_env=True, permission_mode=permission_mode,
                )
            except _CLIUnavailable as without_token:
                # The drop is a probe, not a diagnosis: it only helps when the
                # session on disk is valid. When that session is dead too —
                # the normal state right after `claude setup-token`, and in
                # any container where the env token is the only credential —
                # the probe fails instantly with an auth error and says
                # nothing about the first failure. Surfacing it replaced a
                # timeout with an auth error, and `_retry_timeout` only grows
                # on a timeout: the retry got the same budget that had just
                # run out. Local cycle 20260919T125902Z died that way — a
                # 240s breakdown call timed out, the probe answered in two
                # seconds, the retry got 240s again, and the phase blew its
                # 600s budget. Keep the first failure; it is the one that
                # describes what actually went wrong.
                log.warning(
                    "Claude CLI also failed without the env token (%s) — "
                    "keeping the original failure", without_token,
                )
                raise exc from without_token

    def _retry_timeout(
        self, timeout: int | None, error: Exception, workdir: str | None = None,
    ) -> int:
        """Give a retry more room than the attempt that ran out of it.

        Retrying a timeout with the same budget cannot succeed: the second
        attempt does the same work under the same clock. Prod cycle
        11e5fe09535f died exactly that way — the TechLead breakdown hit its
        120s twice in a row and the cycle failed with no useful diagnosis.
        Only timeouts grow; a crash or an auth failure keeps its budget.
        """
        effective = self._effective_timeout(timeout, workdir)
        if not _is_timeout(error):
            return effective
        grown = min(int(effective * self.timeout_growth), self.timeout_ceiling)
        # Remember it, so the next call starts here instead of relearning that
        # `effective` is too small. Capped: a budget that keeps growing turns a
        # hung call into a phase timeout with no diagnosis attached.
        self._timeout_floor = grown
        if workdir:
            _remember_floor(workdir, grown)
        log.warning(
            "Claude CLI timed out at %ds — retrying with %ds "
            "(floor for later calls in this cycle)", effective, grown,
        )
        return grown

    async def _run_cli(
        self,
        prompt: str,
        *,
        workdir: str | None,
        timeout: int | None,
        drop_oauth_env: bool = False,
        permission_mode: str | None = None,
    ) -> ClaudeResult:
        """Invoke ``claude -p`` and parse the JSON envelope.

        Fails via ``_CLIUnavailable`` so the caller can fall back to API.
        """
        binary = shutil.which("claude")
        if binary is None:
            raise _CLIUnavailable("claude binary not on PATH")

        effective_timeout = self._effective_timeout(timeout, workdir)
        model_id = self._resolve_model()

        cmd = [
            binary, "-p", prompt,
            "--model", model_id,
            "--output-format", "json",
        ]
        if permission_mode:
            cmd += ["--permission-mode", permission_mode]

        prompt_chars = len(prompt or "")
        log.info(
            "Claude CLI: model=%s workdir=%s timeout=%ds prompt_chars=%d",
            model_id, workdir, effective_timeout, prompt_chars,
        )
        if prompt_chars > 30_000:
            log.warning(
                "Claude CLI prompt is large (%d chars) — expect slow response. "
                "Consider trimming context.",
                prompt_chars,
            )

        cli_env = _child_env(drop_oauth_env=drop_oauth_env, workdir=workdir)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=workdir,
                env=cli_env,
            )
        except FileNotFoundError as exc:
            raise _CLIUnavailable(f"spawn failed: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout,
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise _CLIUnavailable(f"CLI timed out after {effective_timeout}s") from exc

        if proc.returncode != 0:
            # The CLI reports failures as a JSON envelope on *stdout* and
            # often leaves stderr empty, so reporting stderr alone produced
            # a bare "exit 1:" that hid the cause for three debugging rounds
            # (the real message was "OAuth access token has expired").
            err = stderr.decode(errors="replace").strip()[:500]
            detail = err or _envelope_error(stdout) or "no output"
            raise _CLIUnavailable(f"exit {proc.returncode}: {detail}")

        raw = stdout.decode(errors="replace").strip()
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _CLIUnavailable(f"JSON parse failed: {exc}") from exc

        if envelope.get("is_error"):
            msg = envelope.get("result") or envelope.get("api_error_status") or "unknown"
            raise _CLIUnavailable(f"CLI reported error: {msg}")

        usage = envelope.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        cost_usd = float(envelope.get("total_cost_usd", 0.0))
        text = envelope.get("result", "") or ""

        log.info(
            "Claude CLI result: $%.4f  model=%s  in=%d out=%d",
            cost_usd, model_id, input_tokens, output_tokens,
        )

        return ClaudeResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            model=model_id,
            backend="cli",
        )

    async def _run_api(
        self,
        prompt: str,
        *,
        workdir: str | None,
        timeout: int | None,
    ) -> ClaudeResult:
        """Anthropic Messages API path with adaptive retry/backoff."""
        effective_timeout = self._effective_timeout(timeout, workdir)
        model_id = self._resolve_model()

        system_parts = []
        if workdir:
            system_parts.append(f"Working directory: {workdir}")

        client = anthropic.AsyncAnthropic()

        log.info(
            "Claude API: model=%s workdir=%s timeout=%ds prompt_chars=%d",
            model_id, workdir, effective_timeout, len(prompt or ""),
        )

        attempt = 0
        while True:
            try:
                response = await asyncio.wait_for(
                    client.messages.create(
                        model=model_id,
                        max_tokens=self.max_tokens,
                        system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
                        messages=[{"role": "user", "content": prompt}],
                    ),
                    timeout=effective_timeout,
                )
                break
            except (anthropic.APIError, asyncio.TimeoutError) as exc:
                fatal_reason = _classify_fatal(exc)
                if fatal_reason is not None:
                    log.error("Claude API fatal (non-retryable): %s", fatal_reason)
                    raise ClaudeFatalError(fatal_reason) from exc
                if not isinstance(exc, _RETRYABLE_ERRORS):
                    raise
                if attempt >= self.max_retries:
                    log.error(
                        "Claude API exhausted retries (%d): %s: %s",
                        self.max_retries, type(exc).__name__, exc,
                    )
                    raise
                delay_ms = self._compute_backoff_ms(attempt)
                log.warning(
                    "Claude API retry %d/%d after %s: %s (sleep %dms, timeout→%ds)",
                    attempt + 1, self.max_retries, type(exc).__name__, exc,
                    delay_ms, int(effective_timeout * self.timeout_growth),
                )
                await self._sleep(delay_ms / 1000.0)
                effective_timeout = int(effective_timeout * self.timeout_growth)
                attempt += 1

        text = response.content[0].text if response.content else ""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost_usd = _estimate_cost(model_id, input_tokens, output_tokens)

        log.info(
            "Claude API result: $%.4f  model=%s  in=%d out=%d  attempts=%d",
            cost_usd, model_id, input_tokens, output_tokens, attempt + 1,
        )

        return ClaudeResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            model=model_id,
            backend="api",
        )

    async def run_tests(
        self,
        workdir: str,
        command: list[str],
        *,
        timeout: int = 300,
    ) -> dict:
        """Run a shell test command and return pass/fail + output."""
        log.info("Running tests in %s: %s", workdir, " ".join(command))

        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=workdir,
        )

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"passed": False, "output": f"Timed out after {timeout}s", "exit_code": -1}

        output = stdout.decode(errors="replace")
        return {
            "passed": proc.returncode == 0,
            "output": output[-5000:],
            "exit_code": proc.returncode,
        }
