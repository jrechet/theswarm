"""LLM-powered context condensation using Haiku for token budget management."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import anthropic

from theswarm.tools.claude import _estimate_cost

log = logging.getLogger(__name__)

_CONDENSE_SYSTEM_PROMPT = """\
You are a context condensation engine. Your job is to shorten the provided text \
while preserving all essential information.

Rules:
- Preserve exact code snippets, error messages, and file paths verbatim
- Preserve structured data (JSON, YAML, lists, tables) intact
- Summarize prose, descriptions, and narrative sections into concise bullet points
- Keep technical details (function names, variable names, types, versions)
- Remove filler words, redundant explanations, and repeated information
- Output should use clear sections with headers where appropriate
- Never invent information that was not in the original text"""

_CONDENSE_DIFF_SYSTEM_PROMPT = """\
You are a diff condensation engine. Your job is to shorten a PR diff while \
preserving the information needed for code review.

Rules:
- Preserve all filenames and their paths exactly
- Preserve hunks that show logic changes (new functions, modified conditions, \
changed return values, new imports)
- Remove whitespace-only changes, formatting-only changes, and trivial renames
- Keep error handling changes and security-relevant modifications
- Summarize large blocks of repetitive changes (e.g. "renamed X to Y in 15 places")
- Output as a condensed diff-like format with file headers and key hunks"""

_CONDENSE_TIMEOUT_S = 30
_MAX_OUTPUT_TOKENS = 4096


@dataclass(frozen=True)
class CondensationResult:
    """Result of a condensation operation."""

    original_chars: int
    condensed_chars: int
    savings_percent: float
    condensed_text: str


class ContextCondenser:
    """Condenses long context strings using a cheap LLM to stay within token budgets."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        max_target_chars: int = 3000,
    ) -> None:
        self._model = model
        self._max_target_chars = max_target_chars

    async def condense(
        self,
        text: str,
        *,
        preserve_code: bool = True,
    ) -> CondensationResult:
        """Condense text if it exceeds the target character threshold.

        Returns the original text unchanged (no API call) if already short enough.
        """
        original_chars = len(text)

        if original_chars <= self._max_target_chars:
            return CondensationResult(
                original_chars=original_chars,
                condensed_chars=original_chars,
                savings_percent=0.0,
                condensed_text=text,
            )

        user_prompt = (
            f"Condense the following text to approximately {self._max_target_chars} characters "
            f"or fewer.\n\n"
        )
        if preserve_code:
            user_prompt += "IMPORTANT: Preserve all code snippets exactly as-is.\n\n"
        user_prompt += text

        condensed = await self._call_llm(
            system=_CONDENSE_SYSTEM_PROMPT,
            user_message=user_prompt,
        )

        condensed_chars = len(condensed)
        savings = (1.0 - condensed_chars / original_chars) * 100.0 if original_chars > 0 else 0.0

        log.info(
            "Condensed: %d -> %d chars (%.1f%% savings)",
            original_chars,
            condensed_chars,
            savings,
        )

        return CondensationResult(
            original_chars=original_chars,
            condensed_chars=condensed_chars,
            savings_percent=savings,
            condensed_text=condensed,
        )

    async def condense_diff(self, diff_text: str, max_chars: int = 8000) -> str:
        """Condense a PR diff, preserving file names and key changes.

        Returns the original diff unchanged if already under the character limit.
        """
        if len(diff_text) <= max_chars:
            return diff_text

        user_prompt = (
            f"Condense this diff to approximately {max_chars} characters or fewer. "
            f"Preserve all filenames and logic-changing hunks.\n\n"
            f"{diff_text}"
        )

        condensed = await self._call_llm(
            system=_CONDENSE_DIFF_SYSTEM_PROMPT,
            user_message=user_prompt,
        )

        log.info(
            "Condensed diff: %d -> %d chars",
            len(diff_text),
            len(condensed),
        )

        return condensed

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimate: chars / 4."""
        return len(text) // 4

    async def _call_llm(self, *, system: str, user_message: str) -> str:
        """Make a single LLM call with timeout and cost tracking."""
        client = anthropic.AsyncAnthropic()

        response = await asyncio.wait_for(
            client.messages.create(
                model=self._model,
                max_tokens=_MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            ),
            timeout=_CONDENSE_TIMEOUT_S,
        )

        text = response.content[0].text if response.content else ""

        cost = _estimate_cost(
            self._model,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        log.info(
            "Condenser LLM: model=%s in=%d out=%d cost=$%.4f",
            self._model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            cost,
        )

        return text
