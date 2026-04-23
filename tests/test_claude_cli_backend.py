"""Tests for the Claude Code CLI backend and API-fallback behavior."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools.claude import ClaudeCLI, _CLIUnavailable


def _api_response(text: str = "ok", in_tok: int = 10, out_tok: int = 20):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


class _FakeProc:
    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        pass


def _cli_envelope(
    *, text: str = "hi", in_tok: int = 5, out_tok: int = 7, cost: float = 0.0012,
    is_error: bool = False,
) -> bytes:
    env = {
        "type": "result",
        "subtype": "success" if not is_error else "error",
        "is_error": is_error,
        "result": text,
        "total_cost_usd": cost,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    }
    return json.dumps(env).encode()


class TestCLIBackendSuccess:
    async def test_cli_parses_json_envelope(self, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
        cli = ClaudeCLI(model="haiku")

        with (
            patch("theswarm.tools.claude.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "theswarm.tools.claude.asyncio.create_subprocess_exec",
                AsyncMock(return_value=_FakeProc(stdout=_cli_envelope(
                    text="hello from cli", in_tok=12, out_tok=34, cost=0.0021,
                ))),
            ),
        ):
            result = await cli.run("say hi")

        assert result.text == "hello from cli"
        assert result.input_tokens == 12
        assert result.output_tokens == 34
        assert result.total_tokens == 46
        assert result.cost_usd == pytest.approx(0.0021)
        assert result.backend == "cli"

    async def test_cli_forced_mode_does_not_fall_back(self, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "cli")
        cli = ClaudeCLI(model="haiku")

        with patch("theswarm.tools.claude.shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="CLI unavailable"):
                await cli.run("anything")


class TestCLIFallbackToAPI:
    async def test_binary_missing_falls_back(self, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
        cli = ClaudeCLI(model="haiku", max_retries=0)

        with (
            patch("theswarm.tools.claude.shutil.which", return_value=None),
            patch("anthropic.AsyncAnthropic") as mock_client,
        ):
            mock_client.return_value.messages.create = AsyncMock(
                return_value=_api_response(text="api-reply"),
            )
            result = await cli.run("hi")

        assert result.text == "api-reply"
        assert result.backend == "api"

    async def test_cli_nonzero_exit_falls_back(self, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
        cli = ClaudeCLI(model="haiku", max_retries=0)

        with (
            patch("theswarm.tools.claude.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "theswarm.tools.claude.asyncio.create_subprocess_exec",
                AsyncMock(return_value=_FakeProc(
                    stdout=b"", stderr=b"auth required", returncode=1,
                )),
            ),
            patch("anthropic.AsyncAnthropic") as mock_client,
        ):
            mock_client.return_value.messages.create = AsyncMock(
                return_value=_api_response(text="from-api"),
            )
            result = await cli.run("hi")

        assert result.text == "from-api"
        assert result.backend == "api"

    async def test_cli_bad_json_falls_back(self, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
        cli = ClaudeCLI(model="haiku", max_retries=0)

        with (
            patch("theswarm.tools.claude.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "theswarm.tools.claude.asyncio.create_subprocess_exec",
                AsyncMock(return_value=_FakeProc(stdout=b"not json", returncode=0)),
            ),
            patch("anthropic.AsyncAnthropic") as mock_client,
        ):
            mock_client.return_value.messages.create = AsyncMock(
                return_value=_api_response(text="fallback"),
            )
            result = await cli.run("hi")

        assert result.text == "fallback"
        assert result.backend == "api"

    async def test_cli_reports_is_error_falls_back(self, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
        cli = ClaudeCLI(model="haiku", max_retries=0)

        env = _cli_envelope(is_error=True, text="quota exhausted")

        with (
            patch("theswarm.tools.claude.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "theswarm.tools.claude.asyncio.create_subprocess_exec",
                AsyncMock(return_value=_FakeProc(stdout=env, returncode=0)),
            ),
            patch("anthropic.AsyncAnthropic") as mock_client,
        ):
            mock_client.return_value.messages.create = AsyncMock(
                return_value=_api_response(text="via-api"),
            )
            result = await cli.run("hi")

        assert result.backend == "api"
        assert result.text == "via-api"


class TestAPIForcedMode:
    async def test_api_mode_skips_cli_entirely(self, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "api")
        cli = ClaudeCLI(model="haiku", max_retries=0)

        # If the CLI path were attempted, shutil.which would be called.
        with (
            patch("theswarm.tools.claude.shutil.which") as which_mock,
            patch("anthropic.AsyncAnthropic") as mock_client,
        ):
            mock_client.return_value.messages.create = AsyncMock(
                return_value=_api_response(text="api-only"),
            )
            result = await cli.run("hi")

        which_mock.assert_not_called()
        assert result.backend == "api"
