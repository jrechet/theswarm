"""`auto` is sdk → api (V2 runtime M1, then M7 retired the CLI in between).

The SDK answers first. A quota stays fatal, a spent timeout is not spent a
second time, and any other SDK failure goes to the Messages API only when a
usable key exists — otherwise the SDK's own failure is the one to read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI, ClaudeFatalError, SDKTimeoutError


@pytest.fixture()
def auto(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return ClaudeCLI(model="haiku")


def _result(backend: str) -> claude_mod.ClaudeResult:
    return claude_mod.ClaudeResult(text=f"from {backend}", backend=backend)


async def test_the_sdk_answers_first(auto):
    with patch.object(auto, "_sdk_with_recovery", new=AsyncMock(return_value=_result("sdk"))), \
         patch.object(auto, "_run_api", new=AsyncMock()) as api_spy:
        result = await auto.run("hi")

    assert result.backend == "sdk"
    assert api_spy.await_count == 0


async def test_the_structured_request_reaches_the_sdk(auto):
    schema = {"type": "object"}
    with patch.object(auto, "_sdk_with_recovery", new=AsyncMock(return_value=_result("sdk"))) as sdk:
        await auto.run("hi", output_schema=schema)

    assert sdk.await_args.kwargs["output_schema"] == schema


async def test_a_failed_sdk_falls_back_to_the_api_with_a_usable_key(auto, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    broken = AsyncMock(side_effect=RuntimeError("Claude SDK failed: not installed"))
    with patch.object(auto, "_sdk_with_recovery", new=broken), \
         patch.object(auto, "_run_api", new=AsyncMock(return_value=_result("api"))):
        result = await auto.run("hi")

    assert result.backend == "api"


async def test_without_a_usable_key_the_sdk_failure_surfaces(auto):
    broken = AsyncMock(side_effect=RuntimeError("Claude SDK failed: not installed"))
    with patch.object(auto, "_sdk_with_recovery", new=broken), \
         patch.object(auto, "_run_api", new=AsyncMock()) as api_spy:
        with pytest.raises(RuntimeError, match="not installed"):
            await auto.run("hi")

    assert api_spy.await_count == 0


async def test_a_spent_timeout_is_not_spent_again(auto, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    spent = AsyncMock(side_effect=SDKTimeoutError("Claude SDK failed twice: timed out"))
    with patch.object(auto, "_sdk_with_recovery", new=spent), \
         patch.object(auto, "_run_api", new=AsyncMock()) as api_spy:
        with pytest.raises(SDKTimeoutError):
            await auto.run("hi")

    assert api_spy.await_count == 0


async def test_an_exhausted_subscription_stops_everything(auto, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    quota = AsyncMock(side_effect=ClaudeFatalError("Claude subscription exhausted: resets 7pm"))
    with patch.object(auto, "_sdk_with_recovery", new=quota), \
         patch.object(auto, "_run_api", new=AsyncMock()) as api_spy:
        with pytest.raises(ClaudeFatalError):
            await auto.run("hi")

    assert api_spy.await_count == 0


def test_a_timeout_error_is_still_a_runtime_error():
    """Callers that skip a failed step catch RuntimeError (#147)."""
    assert issubclass(SDKTimeoutError, RuntimeError)


async def test_the_retired_cli_mode_runs_on_the_sdk(monkeypatch):
    """An environment that still says `cli` (the way back before V2 M7)
    must not fail every call: it runs on the SDK, with a warning."""
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "cli")
    cli = ClaudeCLI(model="haiku")
    with patch.object(cli, "_sdk_with_recovery", new=AsyncMock(return_value=_result("sdk"))) as sdk:
        result = await cli.run("hi")

    assert result.backend == "sdk"
    assert sdk.await_count == 1
