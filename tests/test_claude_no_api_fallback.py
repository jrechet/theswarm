"""The API fallback must not fire when the API cannot authenticate.

Prod repro (cycle 65ab4b0fdf3e): the CLI hung transiently under load, the
auto-mode fallback hit the Messages API with the deployment's
``sk-ant-oat`` OAuth token — which the ``x-api-key`` header rejects by
design — and the resulting 401 killed the whole cycle. A transient CLI
failure must retry the CLI, not switch to a backend that can never work.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools.claude import (
    ClaudeCLI,
    ClaudeResult,
    _api_backend_viable,
    _CLIUnavailable,
)


# ── _api_backend_viable ────────────────────────────────────────────────


def test_oauth_token_is_not_viable_for_api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-abc123")
    assert _api_backend_viable() is False


def test_real_api_key_is_viable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-abc123")
    assert _api_backend_viable() is True


def test_missing_key_is_not_viable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert _api_backend_viable() is False


def test_blank_key_is_not_viable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert _api_backend_viable() is False


# ── run() routing ──────────────────────────────────────────────────────


async def test_cli_failure_retries_cli_when_api_not_viable(monkeypatch):
    """With an OAuth token, a transient CLI failure retries the CLI."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-abc123")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)

    cli = ClaudeCLI(model="haiku")
    calls = 0

    async def flaky_cli(*_a, **_kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _CLIUnavailable("CLI timed out after 180s")
        return ClaudeResult(text="recovered", backend="cli")

    api_mock = AsyncMock()
    with patch.object(cli, "_run_cli", side_effect=flaky_cli), \
         patch.object(cli, "_run_api", api_mock):
        result = await cli.run("hi")

    assert result.text == "recovered"
    assert calls == 2
    api_mock.assert_not_awaited()  # never touched the unusable API path


async def test_persistent_cli_failure_surfaces_cli_error_not_401(monkeypatch):
    """Two CLI failures raise the CLI's own error, never an opaque 401."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-abc123")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)

    cli = ClaudeCLI(model="haiku")
    api_mock = AsyncMock()

    with patch.object(cli, "_run_cli", side_effect=_CLIUnavailable("exit 1: boom")), \
         patch.object(cli, "_run_api", api_mock):
        with pytest.raises(RuntimeError, match="CLI failed twice"):
            await cli.run("hi")

    api_mock.assert_not_awaited()


async def test_cli_failure_falls_back_when_api_key_is_real(monkeypatch):
    """A genuine API key keeps the original fallback behaviour."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-abc123")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)

    cli = ClaudeCLI(model="haiku")
    api_mock = AsyncMock(return_value=ClaudeResult(text="from api", backend="api"))

    with patch.object(cli, "_run_cli", side_effect=_CLIUnavailable("exit 1")), \
         patch.object(cli, "_run_api", api_mock):
        result = await cli.run("hi")

    assert result.text == "from api"
    api_mock.assert_awaited_once()


async def test_forced_api_mode_still_uses_api(monkeypatch):
    """SWARM_CLAUDE_BACKEND=api is explicit — the viability check must not veto it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-abc123")
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "api")

    cli = ClaudeCLI(model="haiku")
    api_mock = AsyncMock(return_value=ClaudeResult(text="forced", backend="api"))
    cli_mock = AsyncMock()

    with patch.object(cli, "_run_cli", cli_mock), patch.object(cli, "_run_api", api_mock):
        result = await cli.run("hi")

    assert result.text == "forced"
    cli_mock.assert_not_awaited()
