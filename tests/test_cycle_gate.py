"""Who may start (2026-10-13: "le nombre de cycles max et par projet doivent
être configurables via l'interface"): cycles in all, per repository, never
two on one feature, a cycle without a feature alone — one gate, the owner's
numbers."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from theswarm import api as api_mod
from theswarm import cycle_gate as gate_mod
from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle
from theswarm.cycle_gate import cycle_gate, cycle_workspace, floor_key, set_cycle_limits


class _Limits:
    def __init__(self, in_all=None, **per_repo):
        self.in_all = in_all
        self.per_repo = {k.replace("__", "/"): v for k, v in per_repo.items()}

    def global_max(self):
        return self.in_all

    def repo_max(self, repo):
        return self.per_repo.get(repo)


@pytest.fixture(autouse=True)
def _no_limits():
    yield
    set_cycle_limits(None)


class _Harness:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        self.gates: dict[str, asyncio.Event] = {}

    async def body(self, cycle_id: str, repo: str, *_a, **_kw) -> None:
        self.log.append(("enter", cycle_id))
        await self.gates[cycle_id].wait()
        self.log.append(("exit", cycle_id))

    def start(self, repo: str, issue: int | None):
        record = get_cycle_tracker().create(CycleRequest(repo=repo, issue_number=issue))
        self.gates[record.id] = asyncio.Event()
        task = asyncio.create_task(run_api_cycle(record.id, repo, "", "", [], issue_number=issue))
        return record.id, task

    def entered(self) -> list[str]:
        return [c for kind, c in self.log if kind == "enter"]


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    await asyncio.sleep(0.01)


async def _finish(h: _Harness, tasks) -> None:
    for event in h.gates.values():
        event.set()
    await asyncio.gather(*tasks)


async def test_two_features_on_one_project_run_side_by_side_when_the_owner_allows():
    set_cycle_limits(_Limits(in_all=2, o__app=2))
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, ta = h.start("o/app", 265)
        b, tb = h.start("o/app", 218)
        await _settle()
        assert h.entered() == [a, b]
        await _finish(h, [ta, tb])


async def test_by_default_a_project_runs_one_at_a_time():
    set_cycle_limits(_Limits(in_all=2))
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, ta = h.start("o/app", 265)
        b, tb = h.start("o/app", 218)
        await _settle()
        assert h.entered() == [a]
        await _finish(h, [ta, tb])


async def test_never_two_cycles_on_one_feature():
    set_cycle_limits(_Limits(in_all=3, o__app=3))
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, ta = h.start("o/app", 265)
        b, tb = h.start("o/app", 265)
        c, tc = h.start("o/app", 218)
        await _settle()
        assert h.entered() == [a, c]
        assert cycle_gate().why_waiting(b) == "feature"
        h.gates[a].set()
        await _settle()
        assert b in h.entered()
        await _finish(h, [ta, tb, tc])


async def test_a_cycle_without_a_feature_runs_alone_and_holds_its_line():
    set_cycle_limits(_Limits(in_all=3, o__app=3))
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, ta = h.start("o/app", 265)
        b, tb = h.start("o/app", None)   # the daily backlog: alone
        c, tc = h.start("o/app", 218)    # behind it: it does not pass
        await _settle()
        assert h.entered() == [a]
        h.gates[a].set()
        await _settle()
        assert h.entered() == [a, b]
        h.gates[b].set()
        await _settle()
        assert h.entered() == [a, b, c]
        await _finish(h, [ta, tb, tc])


async def test_the_number_in_all_bounds_every_project():
    set_cycle_limits(_Limits(in_all=2, o__app=3))
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, ta = h.start("o/app", 1)
        b, tb = h.start("o/app", 2)
        c, tc = h.start("o/other", 3)
        await _settle()
        assert h.entered() == [a, b]
        assert cycle_gate().why_waiting(c) == "slot"
        await _finish(h, [ta, tb, tc])


async def test_raising_a_number_lets_the_waiting_in_at_once():
    set_cycle_limits(_Limits(in_all=2))
    h = _Harness()
    with patch.object(api_mod, "_run_api_cycle", h.body):
        a, ta = h.start("o/app", 265)
        b, tb = h.start("o/app", 218)
        await _settle()
        assert h.entered() == [a]
        set_cycle_limits(_Limits(in_all=2, o__app=2))  # the owner saves Settings → Cycles
        await _settle()
        assert h.entered() == [a, b]
        await _finish(h, [ta, tb])


def test_a_project_running_several_gives_each_cycle_a_clone_of_its_own():
    set_cycle_limits(_Limits(o__app=2))
    assert cycle_workspace("/w/alpha/app", "o/app", "abc123abc123") == "/w/alpha/app@abc123abc123"
    assert cycle_workspace("/w/alpha/other", "o/other", "abc123abc123") == "/w/alpha/other"


def test_what_a_clone_learns_is_its_repositorys():
    assert floor_key("/w/alpha/app@abc123abc123") == "/w/alpha/app"
    assert floor_key("/w/alpha/app@abc123abc123/.worktrees/feat--x") == "/w/alpha/app/.worktrees/feat--x"
    assert floor_key("/w/alpha/app") == "/w/alpha/app"


def test_without_the_owners_numbers_the_environment_decides(monkeypatch):
    monkeypatch.setenv("SWARM_MAX_CONCURRENT_CYCLES", "2")
    assert gate_mod.max_concurrent_cycles() == 2 and gate_mod.repo_max_cycles("o/app") == 1
