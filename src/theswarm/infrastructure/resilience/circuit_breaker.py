"""Sprint G3 — circuit breaker for external API calls (GitHub rate limits).

Three states:
    closed     — requests pass through; failures counted.
    open       — requests fast-fail with CircuitOpenError until cool-down elapses.
    half_open  — after cool-down, one probe is allowed; success closes the circuit.

Immediate-trip errors (e.g. GitHub rate-limit exceptions) open the breaker on
the first occurrence. Regular errors only open after `failure_threshold`
consecutive failures.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

T = TypeVar("T")

log = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit is open."""


@dataclass
class CircuitBreaker:
    """Async circuit breaker.

    Parameters
    ----------
    name:
        Human-readable label used in logs.
    failure_threshold:
        Consecutive regular failures that trip the breaker.
    reset_seconds:
        Cool-down before the breaker allows a probe.
    immediate_trip_errors:
        Exception types that open the breaker on the first hit (rate limits).
    clock:
        Injectable time source for testability.
    """

    name: str = "default"
    failure_threshold: int = 5
    reset_seconds: float = 60.0
    immediate_trip_errors: tuple[type[BaseException], ...] = ()
    clock: Callable[[], float] = field(default=time.monotonic)

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Invoke `fn()` through the breaker. Raises CircuitOpenError when open."""
        await self._before_call()
        try:
            result = await fn()
        except self.immediate_trip_errors as exc:
            await self._trip(reason=f"immediate: {type(exc).__name__}")
            raise
        except BaseException as exc:
            await self._on_failure(exc)
            raise
        else:
            await self._on_success()
            return result

    async def _before_call(self) -> None:
        async with self._lock:
            if self.state is CircuitState.OPEN:
                if self._opened_at is None:
                    self._opened_at = self.clock()
                elapsed = self.clock() - self._opened_at
                if elapsed >= self.reset_seconds:
                    log.info("circuit[%s] cool-down elapsed → half_open", self.name)
                    self.state = CircuitState.HALF_OPEN
                else:
                    remaining = self.reset_seconds - elapsed
                    raise CircuitOpenError(
                        f"circuit[{self.name}] open — {remaining:.1f}s until probe",
                    )

    async def _on_success(self) -> None:
        async with self._lock:
            if self.state is not CircuitState.CLOSED:
                log.info("circuit[%s] probe succeeded → closed", self.name)
            self.state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None

    async def _on_failure(self, exc: BaseException) -> None:
        async with self._lock:
            if self.state is CircuitState.HALF_OPEN:
                self._opened_at = self.clock()
                self.state = CircuitState.OPEN
                log.warning(
                    "circuit[%s] probe failed (%s) → open",
                    self.name, type(exc).__name__,
                )
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._opened_at = self.clock()
                self.state = CircuitState.OPEN
                log.warning(
                    "circuit[%s] threshold reached (%d) → open",
                    self.name, self._failure_count,
                )

    async def _trip(self, reason: str) -> None:
        async with self._lock:
            self._opened_at = self.clock()
            self.state = CircuitState.OPEN
            log.warning("circuit[%s] tripped (%s) → open", self.name, reason)
