"""The API fallback must not fire when the API cannot authenticate.

Prod repro (cycle 65ab4b0fdf3e): the CLI hung transiently under load, the
auto-mode fallback hit the Messages API with the deployment's
``sk-ant-oat`` OAuth token — which the ``x-api-key`` header rejects by
design — and the resulting 401 killed the whole cycle. The same rule holds
for the SDK: without a usable key, its own failure is the one to read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools.claude import (
    ClaudeCLI,
    ClaudeResult,
    _api_backend_viable,
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


# ── run() routing (the SDK since V2 M7; the CLI backend is retired) ──


async def test_an_sdk_failure_with_an_oauth_token_never_reaches_the_api(monkeypatch):
    """The SDK's own error surfaces, never an opaque 401 from the API."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-oat01-abc123")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)

    cli = ClaudeCLI(model="haiku")
    api_mock = AsyncMock()
    failing = AsyncMock(side_effect=RuntimeError("Claude SDK failed: stream closed"))
    with patch.object(cli, "_sdk_with_recovery", failing), \
         patch.object(cli, "_run_api", api_mock):
        with pytest.raises(RuntimeError, match="stream closed"):
            await cli.run("hi")

    api_mock.assert_not_awaited()


async def test_an_sdk_failure_falls_back_when_the_api_key_is_real(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)

    cli = ClaudeCLI(model="haiku")
    failing = AsyncMock(side_effect=RuntimeError("Claude SDK failed: stream closed"))
    api = AsyncMock(return_value=ClaudeResult(text="from api", backend="api"))
    with patch.object(cli, "_sdk_with_recovery", failing), patch.object(cli, "_run_api", api):
        result = await cli.run("hi")

    assert result.backend == "api"


async def test_forced_api_mode_still_uses_api(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "api")

    cli = ClaudeCLI(model="haiku")
    sdk = AsyncMock()
    api = AsyncMock(return_value=ClaudeResult(text="from api", backend="api"))
    with patch.object(cli, "_sdk_with_recovery", sdk), patch.object(cli, "_run_api", api):
        result = await cli.run("hi")

    assert result.backend == "api"
    sdk.assert_not_awaited()
