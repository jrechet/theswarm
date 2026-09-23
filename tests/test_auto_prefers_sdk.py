"""`auto` is sdk → cli → api (V2 runtime M1, after three consecutive green
harness cycles on the sdk backend).

The SDK answers first. A quota stays fatal, a spent timeout is not spent a
second time on the CLI, and any other SDK failure falls through to the CLI
chain as it was.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI, ClaudeFatalError, SDKTimeoutError


@pytest.fixture()
def auto(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
    return ClaudeCLI(model="haiku")


def _result(backend: str) -> claude_mod.ClaudeResult:
    return claude_mod.ClaudeResult(text=f"from {backend}", backend=backend)


async def test_the_sdk_answers_first(auto):
    with patch.object(auto, "_sdk_with_recovery", new=AsyncMock(return_value=_result("sdk"))), \
         patch.object(auto, "_cli_with_auth_recovery", new=AsyncMock()) as cli_spy:
        result = await auto.run("hi")

    assert result.backend == "sdk"
    assert cli_spy.await_count == 0


async def test_the_structured_request_reaches_the_sdk(auto):
    schema = {"type": "object"}
    with patch.object(auto, "_sdk_with_recovery", new=AsyncMock(return_value=_result("sdk"))) as sdk:
        await auto.run("hi", output_schema=schema)

    assert sdk.await_args.kwargs["output_schema"] == schema


async def test_a_failed_sdk_falls_back_to_the_cli(auto):
    broken = AsyncMock(side_effect=RuntimeError("Claude SDK failed: not installed"))
    with patch.object(auto, "_sdk_with_recovery", new=broken), \
         patch.object(auto, "_cli_with_auth_recovery", new=AsyncMock(return_value=_result("cli"))):
        result = await auto.run("hi")

    assert result.backend == "cli"


async def test_a_spent_timeout_is_not_spent_again_on_the_cli(auto):
    spent = AsyncMock(side_effect=SDKTimeoutError("Claude SDK failed twice: timed out"))
    with patch.object(auto, "_sdk_with_recovery", new=spent), \
         patch.object(auto, "_cli_with_auth_recovery", new=AsyncMock()) as cli_spy:
        with pytest.raises(SDKTimeoutError):
            await auto.run("hi")

    assert cli_spy.await_count == 0


async def test_an_exhausted_subscription_stops_everything(auto):
    quota = AsyncMock(side_effect=ClaudeFatalError("Claude subscription exhausted: resets 7pm"))
    with patch.object(auto, "_sdk_with_recovery", new=quota), \
         patch.object(auto, "_cli_with_auth_recovery", new=AsyncMock()) as cli_spy:
        with pytest.raises(ClaudeFatalError):
            await auto.run("hi")

    assert cli_spy.await_count == 0


def test_a_timeout_error_is_still_a_runtime_error():
    """Callers that skip a failed step catch RuntimeError (#147)."""
    assert issubclass(SDKTimeoutError, RuntimeError)
