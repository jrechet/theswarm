"""Tests for ClaudeCLI.run() and run_tests() methods."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── ClaudeCLI.run() ──────────────────────────────────────────────────


def _make_mock_response(text="Hello world", input_tokens=100, output_tokens=50,
                        cache_read=0, cache_write=0):
    """Build a mock Anthropic response with cache usage fields."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock_response.usage.input_tokens = input_tokens
    mock_response.usage.output_tokens = output_tokens
    mock_response.usage.cache_read_input_tokens = cache_read
    mock_response.usage.cache_creation_input_tokens = cache_write
    return mock_response


async def test_run_basic():
    from theswarm.tools.claude import ClaudeCLI

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=_make_mock_response())

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="sonnet", timeout=30)
        result = await cli.run("Say hello")

    assert result.text == "Hello world"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.total_tokens == 150
    assert result.cost_usd > 0
    assert result.model == "claude-sonnet-4-20250514"
    assert result.cache_read_tokens == 0
    assert result.cache_write_tokens == 0


async def test_run_with_workdir():
    from theswarm.tools.claude import ClaudeCLI

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_mock_response(text="ok", input_tokens=10, output_tokens=5)
    )

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="haiku")
        result = await cli.run("test", workdir="/tmp/test")

    # System is now a list of blocks with cache_control
    call_kwargs = mock_client.messages.create.call_args[1]
    system_blocks = call_kwargs["system"]
    assert isinstance(system_blocks, list)
    assert "/tmp/test" in system_blocks[0]["text"]
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}


async def test_run_empty_response():
    from theswarm.tools.claude import ClaudeCLI

    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.content = []
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 0
    mock_response.usage.cache_read_input_tokens = 0
    mock_response.usage.cache_creation_input_tokens = 0
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI()
        result = await cli.run("empty")

    assert result.text == ""


async def test_run_custom_model_id():
    from theswarm.tools.claude import ClaudeCLI

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_mock_response(text="ok", input_tokens=10, output_tokens=5)
    )

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="claude-custom-model-v1")
        result = await cli.run("test")

    # Unknown model passes through as-is
    assert result.model == "claude-custom-model-v1"


async def test_run_with_system_uses_cache_control():
    """System prompt is passed as a cached block."""
    from theswarm.tools.claude import ClaudeCLI

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_mock_response(text="done", input_tokens=200, output_tokens=30)
    )

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="sonnet")
        await cli.run("Do the task", system="You are a developer.")

    call_kwargs = mock_client.messages.create.call_args[1]
    system_blocks = call_kwargs["system"]
    assert isinstance(system_blocks, list)
    assert system_blocks[0]["type"] == "text"
    assert "You are a developer." in system_blocks[0]["text"]
    assert system_blocks[0]["cache_control"] == {"type": "ephemeral"}


async def test_run_tracks_cache_tokens():
    """Cache read/write tokens are returned in ClaudeResult."""
    from theswarm.tools.claude import ClaudeCLI

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_mock_response(
            text="cached", input_tokens=50, output_tokens=20,
            cache_read=500, cache_write=0,
        )
    )

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="sonnet")
        result = await cli.run("Do the task", system="You are a developer.")

    assert result.cache_read_tokens == 500
    assert result.cache_write_tokens == 0


async def test_run_cache_reduces_cost():
    """Reading from cache costs 10% of base; verify cost is lower than full re-input."""
    from theswarm.tools.claude import _estimate_cost

    model = "claude-sonnet-4-20250514"
    # 1000 tokens as cache_read vs 1000 tokens as regular input
    cost_cached = _estimate_cost(model, 0, 0, cache_read_tokens=1000)
    cost_full = _estimate_cost(model, 1000, 0)

    assert cost_cached < cost_full
    # Cache read should be ~10% of regular input cost
    assert abs(cost_cached / cost_full - 0.10) < 0.01


# ── ClaudeCLI.run_tests() ───────────────────────────────────────────


async def test_run_tests_success(tmp_path):
    from theswarm.tools.claude import ClaudeCLI

    cli = ClaudeCLI()
    result = await cli.run_tests(
        str(tmp_path),
        ["python", "-c", "print('all tests passed')"],
        timeout=10,
    )

    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert "all tests passed" in result["output"]


async def test_run_tests_failure(tmp_path):
    from theswarm.tools.claude import ClaudeCLI

    cli = ClaudeCLI()
    result = await cli.run_tests(
        str(tmp_path),
        ["python", "-c", "import sys; print('FAIL'); sys.exit(1)"],
        timeout=10,
    )

    assert result["passed"] is False
    assert result["exit_code"] == 1
    assert "FAIL" in result["output"]


async def test_run_tests_timeout(tmp_path):
    from theswarm.tools.claude import ClaudeCLI

    cli = ClaudeCLI()
    result = await cli.run_tests(
        str(tmp_path),
        ["python", "-c", "import time; time.sleep(10)"],
        timeout=1,
    )

    assert result["passed"] is False
    assert "Timed out" in result["output"]
    assert result["exit_code"] == -1
