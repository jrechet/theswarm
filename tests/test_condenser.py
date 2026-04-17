"""Tests for theswarm.tools.condenser — context condensation tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.tools.condenser import CondensationResult, ContextCondenser


# ── estimate_tokens ─────────────────────────────────────────────────


class TestEstimateTokens:
    def test_empty_string(self):
        assert ContextCondenser.estimate_tokens("") == 0

    def test_short_string(self):
        # 12 chars -> 3 tokens
        assert ContextCondenser.estimate_tokens("hello world!") == 3

    def test_longer_string(self):
        text = "a" * 400
        assert ContextCondenser.estimate_tokens(text) == 100

    def test_integer_division(self):
        # 5 chars -> 1 token (integer division)
        assert ContextCondenser.estimate_tokens("abcde") == 1


# ── condense: short text bypass ─────────────────────────────────────


class TestCondenseShortText:
    async def test_short_text_returns_unchanged(self):
        condenser = ContextCondenser(max_target_chars=3000)
        result = await condenser.condense("Short text that fits.")

        assert result.condensed_text == "Short text that fits."
        assert result.original_chars == len("Short text that fits.")
        assert result.condensed_chars == result.original_chars
        assert result.savings_percent == 0.0

    async def test_exact_threshold_returns_unchanged(self):
        condenser = ContextCondenser(max_target_chars=10)
        text = "a" * 10
        result = await condenser.condense(text)

        assert result.condensed_text == text
        assert result.savings_percent == 0.0

    async def test_empty_string_returns_unchanged(self):
        condenser = ContextCondenser(max_target_chars=3000)
        result = await condenser.condense("")

        assert result.condensed_text == ""
        assert result.original_chars == 0
        assert result.savings_percent == 0.0

    async def test_no_api_call_for_short_text(self):
        """Verify the Anthropic API is never called for short text."""
        with patch("theswarm.tools.condenser.anthropic.AsyncAnthropic") as mock_cls:
            condenser = ContextCondenser(max_target_chars=3000)
            await condenser.condense("Short.")

            mock_cls.assert_not_called()


# ── condense: long text triggers LLM ────────────────────────────────


def _make_mock_response(text: str, input_tokens: int = 200, output_tokens: int = 100):
    """Create a mock Anthropic API response."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock_response.usage.input_tokens = input_tokens
    mock_response.usage.output_tokens = output_tokens
    return mock_response


class TestCondenseLongText:
    async def test_long_text_calls_api(self):
        long_text = "x" * 5000
        condensed_output = "Condensed summary of the content."

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_mock_response(condensed_output),
        )

        with patch(
            "theswarm.tools.condenser.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            condenser = ContextCondenser(max_target_chars=3000)
            result = await condenser.condense(long_text)

        assert result.condensed_text == condensed_output
        assert result.original_chars == 5000
        assert result.condensed_chars == len(condensed_output)
        assert result.savings_percent > 0.0
        mock_client.messages.create.assert_awaited_once()

    async def test_uses_haiku_model_by_default(self):
        long_text = "y" * 4000

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_mock_response("short"),
        )

        with patch(
            "theswarm.tools.condenser.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            condenser = ContextCondenser()
            await condenser.condense(long_text)

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    async def test_preserve_code_instruction_in_prompt(self):
        long_text = "z" * 4000

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_mock_response("short"),
        )

        with patch(
            "theswarm.tools.condenser.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            condenser = ContextCondenser(max_target_chars=3000)
            await condenser.condense(long_text, preserve_code=True)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_msg = call_kwargs["messages"][0]["content"]
        assert "Preserve all code snippets" in user_msg

    async def test_no_preserve_code_instruction_when_disabled(self):
        long_text = "w" * 4000

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_mock_response("short"),
        )

        with patch(
            "theswarm.tools.condenser.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            condenser = ContextCondenser(max_target_chars=3000)
            await condenser.condense(long_text, preserve_code=False)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_msg = call_kwargs["messages"][0]["content"]
        assert "Preserve all code snippets" not in user_msg

    async def test_savings_percent_calculation(self):
        long_text = "a" * 10000
        # 2000 char output from 10000 -> 80% savings
        condensed_output = "b" * 2000

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_mock_response(condensed_output),
        )

        with patch(
            "theswarm.tools.condenser.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            condenser = ContextCondenser(max_target_chars=3000)
            result = await condenser.condense(long_text)

        assert result.savings_percent == pytest.approx(80.0, abs=0.1)


# ── condense_diff ───────────────────────────────────────────────────


class TestCondenseDiff:
    async def test_short_diff_returns_unchanged(self):
        diff = "diff --git a/foo.py b/foo.py\n+added line\n"
        condenser = ContextCondenser()
        result = await condenser.condense_diff(diff, max_chars=8000)

        assert result == diff

    async def test_short_diff_no_api_call(self):
        diff = "diff --git a/foo.py b/foo.py\n+added line\n"

        with patch("theswarm.tools.condenser.anthropic.AsyncAnthropic") as mock_cls:
            condenser = ContextCondenser()
            await condenser.condense_diff(diff, max_chars=8000)

            mock_cls.assert_not_called()

    async def test_long_diff_calls_api(self):
        diff = "diff --git a/foo.py b/foo.py\n" + ("+line\n" * 5000)
        condensed_diff = (
            "diff --git a/foo.py b/foo.py\n"
            "+key logic change\n"
            "# 4999 similar additions omitted\n"
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_mock_response(condensed_diff),
        )

        with patch(
            "theswarm.tools.condenser.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            condenser = ContextCondenser()
            result = await condenser.condense_diff(diff, max_chars=8000)

        assert result == condensed_diff
        mock_client.messages.create.assert_awaited_once()

    async def test_diff_preserves_filenames_in_prompt(self):
        diff = "diff --git a/src/main.py b/src/main.py\n" + ("+x\n" * 5000)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_mock_response("condensed"),
        )

        with patch(
            "theswarm.tools.condenser.anthropic.AsyncAnthropic",
            return_value=mock_client,
        ):
            condenser = ContextCondenser()
            await condenser.condense_diff(diff, max_chars=8000)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_msg = call_kwargs["messages"][0]["content"]
        assert "src/main.py" in user_msg
        assert "Preserve all filenames" in user_msg


# ── CondensationResult dataclass ────────────────────────────────────


class TestCondensationResult:
    def test_frozen(self):
        result = CondensationResult(
            original_chars=100,
            condensed_chars=50,
            savings_percent=50.0,
            condensed_text="short",
        )
        with pytest.raises(AttributeError):
            result.condensed_text = "mutated"  # type: ignore[misc]

    def test_fields(self):
        result = CondensationResult(
            original_chars=1000,
            condensed_chars=300,
            savings_percent=70.0,
            condensed_text="condensed content",
        )
        assert result.original_chars == 1000
        assert result.condensed_chars == 300
        assert result.savings_percent == 70.0
        assert result.condensed_text == "condensed content"
