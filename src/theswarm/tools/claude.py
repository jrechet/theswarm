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
# Cache write costs 25% more than base input; cache read costs 10% of base input
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.10


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
    ) -> ClaudeResult:
        """Run a prompt via Anthropic Messages API.

        Args:
            prompt: The user message (dynamic, task-specific content).
            system: Static system prompt cached with ``cache_control``.
                    Ideal for agent role descriptions + project context that
                    remain unchanged across calls within a cycle.
            workdir: Appended to the system prompt as "Working directory: …".
            timeout: Per-call timeout override (seconds).
        """
        effective_timeout = timeout or self.timeout
        model_id = self._resolve_model()

        # Build system content with prompt caching enabled.
        # All static content (role description + project context) goes here so
        # Anthropic can cache it across repeated calls with identical prefixes.
        system_text_parts = []
        if system:
            system_text_parts.append(system)
        if workdir:
            system_text_parts.append(f"Working directory: {workdir}")

        if system_text_parts:
            system_param: object = [
                {
                    "type": "text",
                    "text": "\n\n".join(system_text_parts),
                    "cache_control": {"type": "ephemeral"},
                }
            ]
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

        log.info(
            "Claude result: $%.4f  model=%s  in=%d out=%d  cache_read=%d cache_write=%d",
            cost_usd, model_id, input_tokens, output_tokens, cache_read, cache_write,
        )

        return ClaudeResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
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
