"""Claude API wrapper for SWARM MVP — runs prompts via Anthropic SDK."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

import anthropic

log = logging.getLogger(__name__)

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
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


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
# Cache write costs 25% more than base input; cache read costs 10% of base input.
# A cache entry written but never read before it expires therefore costs 25% MORE
# than not caching at all — only enable caching where several calls share the
# same system prefix in quick succession (default TTL is 5 minutes).
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10

# Anthropic silently ignores cache_control on prefixes below this size —
# no error is returned, so we detect it from the usage counters instead.
_MIN_CACHEABLE_TOKENS = 1024


def _estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    base = _INPUT_COST.get(model, 3.0)
    inp = base * input_tokens / 1_000_000
    out = _OUTPUT_COST.get(model, 15.0) * output_tokens / 1_000_000
    cache_write = base * _CACHE_WRITE_MULT * cache_write_tokens / 1_000_000
    cache_read = base * _CACHE_READ_MULT * cache_read_tokens / 1_000_000
    return inp + out + cache_write + cache_read


@dataclass
class ClaudeCLI:
    """Async wrapper around the Anthropic Messages API."""
    model: str = "sonnet"
    timeout: int = 600  # 10 min default
    max_tokens: int = 8192

    def _resolve_model(self) -> str:
        return _MODEL_MAP.get(self.model, self.model)

    async def run(
        self,
        prompt: str,
        *,
        system: str | None = None,
        workdir: str | None = None,
        timeout: int | None = None,
        cache: bool = False,
    ) -> ClaudeResult:
        """Run a prompt via Anthropic Messages API.

        Args:
            prompt: The user message (dynamic, task-specific content).
            system: Static system prompt — agent role description + project
                    context that stays identical across calls.
            workdir: Appended to the system prompt as "Working directory: …".
            timeout: Per-call timeout override (seconds).
            cache: Mark the system prompt with ``cache_control``. Only enable
                   this when several calls share the same system prefix within
                   the 5-minute cache TTL (e.g. a review loop over N PRs).
                   A single call per prefix costs 25% MORE with caching on,
                   because the write is billed at 1.25x and never read back.
        """
        effective_timeout = timeout or self.timeout
        model_id = self._resolve_model()

        # Static content (role description + project context) goes in the
        # system prompt so it can form a stable, cacheable prefix.
        system_text_parts = []
        if system:
            system_text_parts.append(system)
        if workdir:
            system_text_parts.append(f"Working directory: {workdir}")

        if system_text_parts:
            block: dict = {"type": "text", "text": "\n\n".join(system_text_parts)}
            if cache:
                block["cache_control"] = {"type": "ephemeral"}
            system_param: object = [block]
        else:
            system_param = anthropic.NOT_GIVEN

        client = anthropic.AsyncAnthropic()

        log.info("Claude API: model=%s workdir=%s timeout=%ds", model_id, workdir, effective_timeout)

        response = await asyncio.wait_for(
            client.messages.create(
                model=model_id,
                max_tokens=self.max_tokens,
                system=system_param,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=effective_timeout,
        )

        text = response.content[0].text if response.content else ""
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        # cache_* attributes only present when prompt caching is active
        cache_read = getattr(response.usage, "cache_read_input_tokens", None) or 0
        cache_write = getattr(response.usage, "cache_creation_input_tokens", None) or 0
        cost_usd = _estimate_cost(model_id, input_tokens, output_tokens, cache_read, cache_write)

        # Caching was requested but the API neither wrote nor read a cache entry:
        # the prefix was below the model minimum and cache_control was dropped.
        if cache and cache_read == 0 and cache_write == 0:
            log.warning(
                "Prompt caching requested but no cache entry was created — system "
                "prefix is likely below the %d-token minimum, so cache_control was "
                "silently ignored.", _MIN_CACHEABLE_TOKENS,
            )

        log.info(
            "Claude result: $%.4f  model=%s  in=%d out=%d  cache_read=%d cache_write=%d",
            cost_usd, model_id, input_tokens, output_tokens, cache_read, cache_write,
        )

        return ClaudeResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # input_tokens excludes cached tokens, so they must be added back —
            # otherwise per-role budget enforcement silently under-counts.
            total_tokens=input_tokens + cache_read + cache_write + output_tokens,
            cost_usd=cost_usd,
            model=model_id,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
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
