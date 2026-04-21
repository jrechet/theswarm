"""Claude API wrapper for SWARM MVP — runs prompts via Anthropic SDK."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import anthropic

log = logging.getLogger(__name__)

# Sprint G2 — errors that warrant an adaptive retry with backoff.
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


# Approximate pricing per 1M tokens (USD)
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


@dataclass
class ClaudeCLI:
    """Async wrapper around the Anthropic Messages API."""
    model: str = "sonnet"
    timeout: int = 600  # 10 min default
    max_tokens: int = 8192
    # Sprint G2 — adaptive retry/backoff config.
    max_retries: int = 3
    retry_base_ms: int = 1000
    timeout_growth: float = 1.5
    _sleep: Callable[[float], Awaitable[None]] = field(default=asyncio.sleep, repr=False)
    _rng: random.Random = field(default_factory=random.Random, repr=False)

    def _resolve_model(self) -> str:
        return _MODEL_MAP.get(self.model, self.model)

    def for_task(self, task_category: str, routing: dict[str, str] | None = None) -> ClaudeCLI:
        """Return a new ClaudeCLI configured for a specific task category.

        Uses the routing table to select the right model. Falls back to
        the current model if the category isn't in the table.
        """
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
        """Run a prompt via Anthropic Messages API with adaptive retry.

        On retryable errors (timeout, rate limit, connection, 5xx),
        backs off exponentially with jitter and grows the per-attempt
        timeout by `timeout_growth`. Non-retryable errors propagate.
        """
        effective_timeout = timeout or self.timeout
        model_id = self._resolve_model()

        system_parts = []
        if workdir:
            system_parts.append(f"Working directory: {workdir}")

        client = anthropic.AsyncAnthropic()

        log.info("Claude API: model=%s workdir=%s timeout=%ds", model_id, workdir, effective_timeout)

        attempt = 0
        last_error: BaseException | None = None
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
                last_error = exc
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
            "Claude result: $%.4f  model=%s  in=%d out=%d  attempts=%d",
            cost_usd, model_id, input_tokens, output_tokens, attempt + 1,
        )

        return ClaudeResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            model=model_id,
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
