"""Sprint G3 — circuit breaker tests."""

from __future__ import annotations

import pytest

from theswarm.infrastructure.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


class _RateLimit(Exception):
    pass


async def _ok():
    return "ok"


async def _boom():
    raise ValueError("transient")


async def _ratelimit():
    raise _RateLimit()


async def test_closed_passes_through_and_resets_count():
    cb = CircuitBreaker(failure_threshold=3)
    for _ in range(10):
        assert await cb.call(_ok) == "ok"
    assert cb.state is CircuitState.CLOSED


async def test_opens_after_threshold_failures():
    cb = CircuitBreaker(failure_threshold=3, reset_seconds=10.0)
    for _ in range(3):
        with pytest.raises(ValueError):
            await cb.call(_boom)
    assert cb.state is CircuitState.OPEN


async def test_open_rejects_fast():
    clk = _FakeClock()
    cb = CircuitBreaker(failure_threshold=1, reset_seconds=10.0, clock=clk)
    with pytest.raises(ValueError):
        await cb.call(_boom)
    assert cb.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)


async def test_half_open_after_cool_down():
    clk = _FakeClock()
    cb = CircuitBreaker(failure_threshold=1, reset_seconds=10.0, clock=clk)
    with pytest.raises(ValueError):
        await cb.call(_boom)
    clk.advance(11.0)
    # First call should be admitted (probe) and, on success, close circuit
    assert await cb.call(_ok) == "ok"
    assert cb.state is CircuitState.CLOSED


async def test_half_open_probe_failure_reopens():
    clk = _FakeClock()
    cb = CircuitBreaker(failure_threshold=1, reset_seconds=5.0, clock=clk)
    with pytest.raises(ValueError):
        await cb.call(_boom)
    clk.advance(6.0)

    with pytest.raises(ValueError):
        await cb.call(_boom)
    assert cb.state is CircuitState.OPEN
    # Subsequent call is rejected without invoking fn
    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)


async def test_immediate_trip_on_rate_limit():
    cb = CircuitBreaker(
        failure_threshold=10,  # regular failures would require many
        reset_seconds=30.0,
        immediate_trip_errors=(_RateLimit,),
    )
    with pytest.raises(_RateLimit):
        await cb.call(_ratelimit)
    assert cb.state is CircuitState.OPEN

    with pytest.raises(CircuitOpenError):
        await cb.call(_ok)


async def test_success_resets_failure_counter():
    cb = CircuitBreaker(failure_threshold=3, reset_seconds=10.0)
    # 2 failures
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(_boom)
    # One success resets counter
    assert await cb.call(_ok) == "ok"
    # Need 3 more failures to open now
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(_boom)
    assert cb.state is CircuitState.CLOSED
    with pytest.raises(ValueError):
        await cb.call(_boom)
    assert cb.state is CircuitState.OPEN


# ── Errors that say something about the request, not the service ───────
#
# Four expected 422s ("cannot review your own pull request") opened the
# GitHub breaker on 2026-09-15 and blocked the memory save that followed.


class _ClientError(Exception):
    pass


class _Outage(Exception):
    pass


def _ignoring_client_errors() -> CircuitBreaker:
    return CircuitBreaker(
        name="t", failure_threshold=2,
        ignored_errors=lambda exc: isinstance(exc, _ClientError),
    )


async def test_an_ignored_error_is_re_raised_but_not_counted():
    breaker = _ignoring_client_errors()

    async def refuse():
        raise _ClientError("422")

    for _ in range(5):
        with pytest.raises(_ClientError):
            await breaker.call(refuse)

    assert breaker.state is CircuitState.CLOSED


async def test_an_ignored_error_does_not_reset_the_count_either():
    breaker = _ignoring_client_errors()

    async def outage():
        raise _Outage("502")

    async def refuse():
        raise _ClientError("422")

    with pytest.raises(_Outage):
        await breaker.call(outage)
    with pytest.raises(_ClientError):
        await breaker.call(refuse)
    with pytest.raises(_Outage):
        await breaker.call(outage)

    assert breaker.state is CircuitState.OPEN  # two real failures, threshold 2


async def test_real_failures_still_open_the_breaker():
    breaker = _ignoring_client_errors()

    async def outage():
        raise _Outage("502")

    for _ in range(2):
        with pytest.raises(_Outage):
            await breaker.call(outage)

    assert breaker.state is CircuitState.OPEN


async def test_without_a_predicate_every_error_counts():
    breaker = CircuitBreaker(name="t", failure_threshold=1)

    async def refuse():
        raise _ClientError("422")

    with pytest.raises(_ClientError):
        await breaker.call(refuse)

    assert breaker.state is CircuitState.OPEN
