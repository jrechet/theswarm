"""Tests for ClaudeCLI.run() and run_tests() methods."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── ClaudeCLI.run() ──────────────────────────────────────────────────


async def test_run_basic():
    from theswarm.tools.claude import ClaudeCLI

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello world")]
    mock_response.usage.input_tokens = 100
    mock_response.usage.output_tokens = 50

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="sonnet", timeout=30)
        result = await cli.run("Say hello")

    assert result.text == "Hello world"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.total_tokens == 150
    assert result.cost_usd > 0
    assert result.model == "claude-sonnet-4-20250514"


async def test_run_with_workdir():
    from theswarm.tools.claude import ClaudeCLI

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="haiku")
        result = await cli.run("test", workdir="/tmp/test")

    # Verify system prompt includes workdir
    call_kwargs = mock_client.messages.create.call_args[1]
    assert "/tmp/test" in call_kwargs["system"]


async def test_run_empty_response():
    from theswarm.tools.claude import ClaudeCLI

    mock_response = MagicMock()
    mock_response.content = []
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 0

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI()
        result = await cli.run("empty")

    assert result.text == ""


async def test_run_custom_model_id():
    from theswarm.tools.claude import ClaudeCLI

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("theswarm.tools.claude.anthropic.AsyncAnthropic", return_value=mock_client):
        cli = ClaudeCLI(model="claude-custom-model-v1")
        result = await cli.run("test")

    # Unknown model passes through as-is
    assert result.model == "claude-custom-model-v1"


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
