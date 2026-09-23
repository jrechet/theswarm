"""Cycles across repositories share one bound (V2 M5): the box is one
2 GB container and one subscription window. One per repo stays the
correctness rule; this one is capacity, SWARM_MAX_CONCURRENT_CYCLES."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from theswarm import api as api_mod
from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle


class _Harness:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.gates: dict[str, asyncio.Event] = {}

    async def body(self, cycle_id: str, repo: str, *_a, **_kw) -> None:
        self.log.append(("enter", cycle_id))
        await self.gates[cycle_id].wait()
        self.log.append(("exit", cycle_id))

    def cycle(self, repo: str) -> str:
        record = get_cycle_tracker().create(CycleRequest(repo=repo))
        self.gates[record.id] = asyncio.Event()
        return record.id


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)


async def test_by_default_a_second_repository_waits_its_turn(monkeypatch):
    monkeypatch.delenv("SWARM_MAX_CONCURRENT_CYCLES", raising=False)
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, b = h.cycle("o/one"), h.cycle("o/two")
        ta = asyncio.create_task(run_api_cycle(a, "o/one", "", "", []))
        tb = asyncio.create_task(run_api_cycle(b, "o/two", "", "", []))
        await _settle()
        assert h.log == [("enter", a)]

        h.gates[a].set()
        await _settle()
        assert h.log == [("enter", a), ("exit", a), ("enter", b)]

        h.gates[b].set()
        await asyncio.gather(ta, tb)


async def test_the_bound_is_configurable(monkeypatch):
    monkeypatch.setenv("SWARM_MAX_CONCURRENT_CYCLES", "2")
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, b = h.cycle("o/one"), h.cycle("o/two")
        ta = asyncio.create_task(run_api_cycle(a, "o/one", "", "", []))
        tb = asyncio.create_task(run_api_cycle(b, "o/two", "", "", []))
        await _settle()
        assert h.log == [("enter", a), ("enter", b)]

        h.gates[a].set()
        h.gates[b].set()
        await asyncio.gather(ta, tb)


def test_a_bad_value_means_the_default(monkeypatch):
    from theswarm.cycle import DEFAULT_MAX_CONCURRENT_CYCLES, max_concurrent_cycles

    monkeypatch.setenv("SWARM_MAX_CONCURRENT_CYCLES", "many")
    assert max_concurrent_cycles() == DEFAULT_MAX_CONCURRENT_CYCLES
    monkeypatch.setenv("SWARM_MAX_CONCURRENT_CYCLES", "0")
    assert max_concurrent_cycles() == 1
