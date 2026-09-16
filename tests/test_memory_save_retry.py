"""The memory save waits out an open circuit once.

It is the last GitHub call of a cycle. On 2026-09-15 the breaker was open
— four expected 422s from reviews had tripped it — and the cycle's
learnings were thrown away with a traceback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from theswarm import memory_store
from theswarm.infrastructure.resilience.circuit_breaker import CircuitOpenError


def _entry() -> dict:
    return {"category": "stack", "content": "x", "agent": "QA", "cycle_date": "2026-09-15"}


async def test_an_open_circuit_is_waited_out_once():
    github = AsyncMock()
    github.update_file = AsyncMock(side_effect=[CircuitOpenError("open — 40s until probe"), None])

    with patch("theswarm.memory_store.asyncio.sleep", new=AsyncMock()) as sleep:
        saved = await memory_store.save_entries(github, [_entry()])

    assert saved is True
    assert github.update_file.await_count == 2
    sleep.assert_awaited_once_with(memory_store.CIRCUIT_RETRY_DELAY_SECONDS)


async def test_a_circuit_still_open_after_the_wait_gives_up():
    github = AsyncMock()
    github.update_file = AsyncMock(side_effect=CircuitOpenError("open"))

    with patch("theswarm.memory_store.asyncio.sleep", new=AsyncMock()):
        saved = await memory_store.save_entries(github, [_entry()])

    assert saved is False
    assert github.update_file.await_count == 2


async def test_other_errors_do_not_wait():
    github = AsyncMock()
    github.update_file = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("theswarm.memory_store.asyncio.sleep", new=AsyncMock()) as sleep:
        saved = await memory_store.save_entries(github, [_entry()])

    assert saved is False
    sleep.assert_not_awaited()
    assert github.update_file.await_count == 1


async def test_the_happy_path_is_unchanged():
    github = AsyncMock()

    assert await memory_store.save_entries(github, [_entry()]) is True
    github.update_file.assert_awaited_once()
