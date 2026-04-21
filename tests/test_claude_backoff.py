"""Sprint G2 — adaptive retry + exponential backoff for Claude API."""

from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anthropic
import httpx
import pytest

from theswarm.tools.claude import ClaudeCLI


def _fake_response(text: str = "ok", in_tok: int = 10, out_tok: int = 20):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


def _timeout_error() -> anthropic.APITimeoutError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APITimeoutError(req)


def _rate_limit_error() -> anthropic.RateLimitError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(429, request=req)
    return anthropic.RateLimitError(message="rate limited", response=resp, body=None)


def _server_error() -> anthropic.InternalServerError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(500, request=req)
    return anthropic.InternalServerError(message="boom", response=resp, body=None)


def test_compute_backoff_grows_exponentially():
    cli = ClaudeCLI(retry_base_ms=1000)
    cli._rng = random.Random(42)

    # attempt 0: base*2^0 (+ jitter 0..base)
    # attempt 1: base*2^1 (+ jitter)
    # attempt 2: base*2^2 (+ jitter)
    b0 = cli._compute_backoff_ms(0)
    b1 = cli._compute_backoff_ms(1)
    b2 = cli._compute_backoff_ms(2)

    assert 1000 <= b0 <= 2000
    assert 2000 <= b1 <= 3000
    assert 4000 <= b2 <= 5000


async def test_retries_on_timeout_then_succeeds():
    sleeps: list[float] = []
    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    cli = ClaudeCLI(model="haiku", timeout=10, max_retries=3, retry_base_ms=100)
    cli._sleep = fake_sleep
    cli._rng = random.Random(0)

    calls = 0
    async def fake_create(**_kw):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _timeout_error()
        return _fake_response("finally")

    with patch("anthropic.AsyncAnthropic") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        result = await cli.run("hello")

    assert result.text == "finally"
    assert calls == 3
    assert len(sleeps) == 2  # slept after attempt 0 and 1, not after success


async def test_retries_on_rate_limit():
    sleeps: list[float] = []
    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    cli = ClaudeCLI(model="haiku", max_retries=2, retry_base_ms=10)
    cli._sleep = fake_sleep
    cli._rng = random.Random(0)

    calls = 0
    async def fake_create(**_kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _rate_limit_error()
        return _fake_response()

    with patch("anthropic.AsyncAnthropic") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        result = await cli.run("hi")

    assert result.text == "ok"
    assert calls == 2
    assert len(sleeps) == 1


async def test_retries_on_server_error():
    async def fake_sleep(_s: float) -> None:
        return None

    cli = ClaudeCLI(model="haiku", max_retries=2, retry_base_ms=10)
    cli._sleep = fake_sleep
    cli._rng = random.Random(0)

    calls = 0
    async def fake_create(**_kw):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _server_error()
        return _fake_response()

    with patch("anthropic.AsyncAnthropic") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        result = await cli.run("hi")

    assert result.text == "ok"
    assert calls == 2


async def test_does_not_retry_on_non_retryable_error():
    cli = ClaudeCLI(model="haiku", max_retries=3, retry_base_ms=10)
    cli._sleep = AsyncMock()

    async def fake_create(**_kw):
        raise ValueError("malformed input")

    with patch("anthropic.AsyncAnthropic") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        with pytest.raises(ValueError):
            await cli.run("hi")

    cli._sleep.assert_not_called()


async def test_raises_after_exhausting_retries():
    async def fake_sleep(_s: float) -> None:
        return None

    cli = ClaudeCLI(model="haiku", max_retries=2, retry_base_ms=10)
    cli._sleep = fake_sleep
    cli._rng = random.Random(0)

    calls = 0
    async def fake_create(**_kw):
        nonlocal calls
        calls += 1
        raise _timeout_error()

    with patch("anthropic.AsyncAnthropic") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        with pytest.raises(anthropic.APITimeoutError):
            await cli.run("hi")

    # 1 initial + 2 retries = 3
    assert calls == 3


async def test_timeout_grows_between_retries():
    seen_timeouts: list[float] = []

    async def fake_create(**kw):
        raise _timeout_error()

    original_wait_for = None

    cli = ClaudeCLI(model="haiku", timeout=100, max_retries=2, retry_base_ms=1, timeout_growth=2.0)
    async def fake_sleep(_s: float) -> None:
        return None
    cli._sleep = fake_sleep
    cli._rng = random.Random(0)

    import asyncio as _asyncio
    real_wait_for = _asyncio.wait_for

    async def tracking_wait_for(coro, timeout):
        seen_timeouts.append(timeout)
        # Still call the coroutine to raise the underlying error
        try:
            return await real_wait_for(coro, timeout)
        except Exception:
            raise

    with patch("anthropic.AsyncAnthropic") as mock_client, \
         patch("theswarm.tools.claude.asyncio.wait_for", side_effect=tracking_wait_for):
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        with pytest.raises(anthropic.APITimeoutError):
            await cli.run("hi")

    # timeouts should be 100, 200, 400
    assert seen_timeouts == [100, 200, 400]


async def test_for_task_preserves_retry_config():
    base = ClaudeCLI(max_retries=7, retry_base_ms=321, timeout_growth=3.3)
    routed = base.for_task("planning", {"planning": "opus"})
    assert routed.model == "opus"
    assert routed.max_retries == 7
    assert routed.retry_base_ms == 321
    assert routed.timeout_growth == 3.3
