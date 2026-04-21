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
