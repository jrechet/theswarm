"""Two cycles on one repository must take turns.

They share one workspace, and each treats it as its own: reset, clean,
checkout -B, and rm -rf at the end. The morning a deploy resumed a cycle
while a fresh one started on the same repo, both committed real work and
neither opened a PR — each erased the other's branch in turn, and the
Claude CLI they were both leaning on timed out under the double load.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from theswarm import api as api_mod
from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker, run_api_cycle
from theswarm.cycle import repo_lock


class _Harness:
    """Stand in for the real cycle body: record who runs when, and let the
    test decide when each one is allowed to finish."""

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


class TestSameRepository:
    async def test_the_second_cycle_waits_for_the_first(self):
        h = _Harness()
        with patch.object(api_mod, "_run_api_cycle", h.body):
            a, b = h.cycle("o/r"), h.cycle("o/r")
            ta = asyncio.create_task(run_api_cycle(a, "o/r", "", "", []))
            tb = asyncio.create_task(run_api_cycle(b, "o/r", "", "", []))
            await _settle()

            assert h.log == [("enter", a)]

            h.gates[a].set()
            await _settle()
            assert h.log == [("enter", a), ("exit", a), ("enter", b)]

            h.gates[b].set()
            await asyncio.gather(ta, tb)

    async def test_a_waiting_cycle_is_reported_as_queued_not_running(self):
        h = _Harness()
        with patch.object(api_mod, "_run_api_cycle", h.body):
            a, b = h.cycle("o/r"), h.cycle("o/r")
            ta = asyncio.create_task(run_api_cycle(a, "o/r", "", "", []))
            tb = asyncio.create_task(run_api_cycle(b, "o/r", "", "", []))
            await _settle()

            assert get_cycle_tracker().get(b).status == CycleStatus.QUEUED

            h.gates[a].set()
            h.gates[b].set()
            await asyncio.gather(ta, tb)

    async def test_a_cancelled_waiter_leaves_the_queue_and_the_runner_alone(self):
        h = _Harness()
        with patch.object(api_mod, "_run_api_cycle", h.body):
            a, b = h.cycle("o/r"), h.cycle("o/r")
            ta = asyncio.create_task(run_api_cycle(a, "o/r", "", "", []))
            tb = asyncio.create_task(run_api_cycle(b, "o/r", "", "", []))
            await _settle()

            tb.cancel()
            await tb  # absorbed: recorded as cancelled, not raised

            assert get_cycle_tracker().get(b).status == CycleStatus.CANCELLED
            assert ("enter", b) not in h.log

            h.gates[a].set()
            await ta
            assert h.log == [("enter", a), ("exit", a)]

    async def test_three_in_a_row_run_strictly_one_at_a_time(self):
        h = _Harness()
        with patch.object(api_mod, "_run_api_cycle", h.body):
            ids = [h.cycle("o/r") for _ in range(3)]
            tasks = [asyncio.create_task(run_api_cycle(i, "o/r", "", "", [])) for i in ids]
            for i in ids:
                await _settle()
                h.gates[i].set()
            await asyncio.gather(*tasks)

        running_at_once = 0
        peak = 0
        for kind, _ in h.log:
            running_at_once += 1 if kind == "enter" else -1
            peak = max(peak, running_at_once)
        assert peak == 1


class TestDifferentRepositories:
    async def test_cycles_on_different_repos_overlap(self, monkeypatch):
        """The repo lock is per repository. The *global* bound
        (SWARM_MAX_CONCURRENT_CYCLES, V2 M5, default 1) is a separate rule
        with its own tests; lift it here so this one tests the lock alone."""
        monkeypatch.setenv("SWARM_MAX_CONCURRENT_CYCLES", "2")
        h = _Harness()
        with patch.object(api_mod, "_run_api_cycle", h.body):
            a, b = h.cycle("o/one"), h.cycle("o/two")
            ta = asyncio.create_task(run_api_cycle(a, "o/one", "", "", []))
            tb = asyncio.create_task(run_api_cycle(b, "o/two", "", "", []))
            await _settle()

            assert sorted(h.log) == sorted([("enter", a), ("enter", b)])

            h.gates[a].set()
            h.gates[b].set()
            await asyncio.gather(ta, tb)


class TestTheLockItself:
    async def test_one_lock_per_repository(self):
        assert repo_lock("o/r") is repo_lock("o/r")

    async def test_repositories_do_not_share_a_lock(self):
        assert repo_lock("o/one") is not repo_lock("o/two")

    async def test_a_lock_from_a_dead_loop_is_replaced(self):
        """pytest gives every test its own loop; a server restart could too."""
        stale = asyncio.Lock()
        from theswarm import cycle as cycle_mod
        cycle_mod._repo_locks["o/stale"] = (asyncio.new_event_loop(), stale)

        assert repo_lock("o/stale") is not stale

    async def test_the_lock_is_released_when_the_body_raises(self):
        async def boom(*_a, **_kw):
            raise RuntimeError("cycle blew up")

        with patch.object(api_mod, "_run_api_cycle", boom):
            record = get_cycle_tracker().create(CycleRequest(repo="o/r"))
            try:
                await run_api_cycle(record.id, "o/r", "", "", [])
            except RuntimeError:
                pass

        assert not repo_lock("o/r").locked()
