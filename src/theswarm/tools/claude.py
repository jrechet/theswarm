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
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import anthropic

log = logging.getLogger(__name__)

# Retryable Anthropic API errors: back off and try again.
_RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    asyncio.TimeoutError,
)

# Map short names to full model IDs
_MODEL_MAP: dict[str, str] = {
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
    "haiku": "claude-haiku-4-5-20251001",
}


@dataclass
class ClaudeResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    backend: str = ""  # "cli" or "api"


# Approximate pricing per 1M tokens (USD) — used for the API path.
_INPUT_COST: dict[str, float] = {
    "claude-sonnet-4-20250514": 3.0,
    "claude-opus-4-20250514": 15.0,
    "claude-haiku-4-5-20251001": 0.80,
}
_OUTPUT_COST: dict[str, float] = {
    "claude-sonnet-4-20250514": 15.0,
    "claude-opus-4-20250514": 75.0,
    "claude-haiku-4-5-20251001": 4.0,
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp = _INPUT_COST.get(model, 3.0) * input_tokens / 1_000_000
    out = _OUTPUT_COST.get(model, 15.0) * output_tokens / 1_000_000
    return inp + out


class _CLIUnavailable(Exception):
    """Raised when the Claude Code CLI can't service a request.

    Signals the fallback-to-API path in auto mode. The message describes the
    specific failure (binary missing, non-zero exit, bad JSON, etc.).
    """


def _resolve_backend_mode() -> str:
    raw = os.environ.get("SWARM_CLAUDE_BACKEND", "auto").strip().lower()
    if raw in ("cli", "api", "auto"):
        return raw
    return "auto"


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
    # Injected so tests can stub. Not repr-ed.
    _sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, repr=False)
    _rng: random.Random = field(default_factory=random.Random, repr=False)

    def _resolve_model(self) -> str:
        return _MODEL_MAP.get(self.model, self.model)

    def for_task(self, task_category: str, routing: dict[str, str] | None = None) -> ClaudeCLI:
        """Return a new ClaudeCLI configured for a specific task category."""
        if routing is None:
            return ClaudeCLI(
                model=self.model, timeout=self.timeout, max_tokens=self.max_tokens,
                max_retries=self.max_retries, retry_base_ms=self.retry_base_ms,
                timeout_growth=self.timeout_growth,
            )
        model = routing.get(task_category, self.model)
        return ClaudeCLI(
            model=model, timeout=self.timeout, max_tokens=self.max_tokens,
            max_retries=self.max_retries, retry_base_ms=self.retry_base_ms,
            timeout_growth=self.timeout_growth,
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
    ) -> ClaudeResult:
        """Run a prompt. Tries CLI first, falls back to API on failure.

        Honors ``SWARM_CLAUDE_BACKEND`` (``auto`` | ``cli`` | ``api``).
        """
        backend = _resolve_backend_mode()

        if backend != "api":
            try:
                return await self._run_cli(prompt, workdir=workdir, timeout=timeout)
            except _CLIUnavailable as exc:
                if backend == "cli":
                    raise RuntimeError(f"Claude CLI unavailable (forced): {exc}") from exc
                log.warning("Claude CLI unavailable (%s) — falling back to API", exc)

        return await self._run_api(prompt, workdir=workdir, timeout=timeout)

    async def _run_cli(
        self,
        prompt: str,
        *,
        workdir: str | None,
        timeout: int | None,
    ) -> ClaudeResult:
        """Invoke ``claude -p`` and parse the JSON envelope.

        Fails via ``_CLIUnavailable`` so the caller can fall back to API.
        """
        binary = shutil.which("claude")
        if binary is None:
            raise _CLIUnavailable("claude binary not on PATH")

        effective_timeout = timeout or self.timeout
        model_id = self._resolve_model()

        cmd = [
            binary, "-p", prompt,
            "--model", model_id,
            "--output-format", "json",
        ]

        log.info("Claude CLI: model=%s workdir=%s timeout=%ds", model_id, workdir, effective_timeout)

        # Close stdin and set CI=1 so the CLI doesn't hang on any interactive
        # prompt (update banner, login nag, telemetry opt-in, etc.).
        #
        # ANTHROPIC_API_KEY is always stripped from the child env. Rationale:
        #   - sk-ant-api keys defeat the purpose of the CLI backend (we want
        #     subscription billing, not per-call API credits).
        #   - sk-ant-oat tokens from `claude setup-token` look API-shaped but
        #     Anthropic's server rejects them on the x-api-key header with
        #     'Invalid API key · Fix external API key' — they are only
        #     accepted via the Authorization: Bearer flow that the CLI uses
        #     when reading from ~/.claude/.credentials.json.
        # Either way, the CLI must be allowed to fall through to the session
        # file, so the env var always gets removed for the child.
        cli_env = {
            k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"
        }
        cli_env["CI"] = "1"
        cli_env["CLAUDE_CODE_NON_INTERACTIVE"] = "1"

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
            err = stderr.decode(errors="replace").strip()[:500]
            raise _CLIUnavailable(f"exit {proc.returncode}: {err}")

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
        effective_timeout = timeout or self.timeout
        model_id = self._resolve_model()

        system_parts = []
        if workdir:
            system_parts.append(f"Working directory: {workdir}")

        client = anthropic.AsyncAnthropic()

        log.info("Claude API: model=%s workdir=%s timeout=%ds", model_id, workdir, effective_timeout)

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
            except _RETRYABLE_ERRORS as exc:
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
