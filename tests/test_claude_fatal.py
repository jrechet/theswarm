"""ClaudeFatalError — billing/auth API errors abort instead of retrying.

Prod repro (cycles 3859db29d158, a6e06fb5b4b7, ce2d429c6c81): the API
returned 400 invalid_request_error "Your credit balance is too low…" and the
raw BadRequestError crashed phases one after another. These errors are
account-level: they must surface as a typed, non-retryable failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import anthropic
import httpx
import pytest

from theswarm.tools.claude import ClaudeCLI, ClaudeFatalError, _classify_fatal

CREDIT_MSG = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits.'}}"
)


def _bad_request(message: str) -> anthropic.BadRequestError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(400, request=req)
    return anthropic.BadRequestError(message=message, response=resp, body=None)


def _auth_error() -> anthropic.AuthenticationError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(401, request=req)
    return anthropic.AuthenticationError(message="invalid x-api-key", response=resp, body=None)


# ── _classify_fatal ────────────────────────────────────────────────────


def test_credit_balance_bad_request_is_fatal():
    reason = _classify_fatal(_bad_request(CREDIT_MSG))
    assert reason is not None
    assert "billing" in reason.lower() or "account" in reason.lower()


def test_other_bad_request_is_not_fatal():
    assert _classify_fatal(_bad_request("max_tokens exceeds model limit")) is None


def test_authentication_error_is_fatal():
    assert _classify_fatal(_auth_error()) is not None


def test_rate_limit_is_not_fatal():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(429, request=req)
    err = anthropic.RateLimitError(message="rate limited", response=resp, body=None)
    assert _classify_fatal(err) is None


# ── API path raises ClaudeFatalError without retrying ──────────────────


async def test_api_billing_error_raises_fatal_without_retry(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "api")
    cli = ClaudeCLI(model="haiku", max_retries=3, retry_base_ms=10)
    cli._sleep = AsyncMock()

    calls = 0

    async def fake_create(**_kw):
        nonlocal calls
        calls += 1
        raise _bad_request(CREDIT_MSG)

    with patch("anthropic.AsyncAnthropic") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        with pytest.raises(ClaudeFatalError, match="billing"):
            await cli.run("hi")

    assert calls == 1
    cli._sleep.assert_not_called()


async def test_api_non_billing_bad_request_propagates_raw(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "api")
    cli = ClaudeCLI(model="haiku", max_retries=3, retry_base_ms=10)
    cli._sleep = AsyncMock()

    async def fake_create(**_kw):
        raise _bad_request("max_tokens exceeds model limit")

    with patch("anthropic.AsyncAnthropic") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(side_effect=fake_create)
        with pytest.raises(anthropic.BadRequestError):
            await cli.run("hi")

    cli._sleep.assert_not_called()
