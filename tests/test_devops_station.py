"""DevOps in the cycle — the fifth station (docs/plans/2026-10-v3-one-product.md,
"In the product": a fifth station in the theater only in the cycles where it
acts — the preflight, and the deploy watch after a merge).

DevOps tells its acts on the bus like the other agents (`AgentActivity`,
agent `devops`): the preflight's go and what it read, or its no-go and why;
on the swarm's own repository, the watch of the deploy its merges set off,
closed by a later report — landed, or late.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from theswarm import api as api_module
from theswarm.agents import devops as d
from theswarm.application.events.bus import EventBus
from theswarm.application.services import devops_cycles as dc
from theswarm.config import SELF_REPO
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import AgentActivity, CycleCompleted
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _report(*findings, main="", build=""):
    return d.OpsReport(tuple(findings), read_at=NOW, stack="jrec.fr", facts={"main_sha": main, "build_sha": build})


FINE = (d.Finding("claude", "Claude", "ok", "fine"), d.Finding("disk_here", "Disk (here)", "ok", "40%"),
        d.Finding("runners", "Runners", "ok", "1 online"), d.Finding("ci_slot", "CI slot", "unknown", "no ssh"),
        d.Finding("harness", "Harness", "ok", "built"))


class TestWhatDevOpsSays:
    def test_a_go_says_what_it_read(self):
        answer = d.preflight_of(_report(*FINE))
        assert dc.preflight_words(answer) == "Preflight: go — Claude fine · Disk (here) fine · Runners fine · CI slot not read"
        act = dc.preflight_activity("abc123abc123", "o/r", answer)
        assert act.agent == "devops" and act.action == "preflight" and act.metadata == {"go": True, "reasons": []}

    def test_a_no_go_says_why_the_cycle_was_not_started(self):
        answer = d.preflight_of(_report(d.Finding("disk_here", "Disk (here)", "bad", "96% used")))
        assert dc.preflight_words(answer) == "Preflight: no-go, the cycle is not started — Disk (here): 96% used"
        act = dc.preflight_activity("abc123abc123", "o/r", answer)
        assert act.action == "preflight_nogo" and act.metadata["go"] is False

    def test_the_deploy_watch(self):
        act = dc.deploy_watch_activity("abc123abc123", SELF_REPO, (318, 319), "e39a13c" + "0" * 33)
        assert act.action == "deploy_watch" and act.detail == "Watching the deploy: 2 pull requests merged to main — the new build replaces this server"
        assert act.metadata == {"merged": [318, 319], "build_before": "e39a13c" + "0" * 33}
        assert "1 pull request merged" in dc.deploy_watch_activity("x" * 12, SELF_REPO, [1], "").detail

    async def test_telling_never_costs_the_cycle(self):
        async def down(_):
            raise RuntimeError("bus down")

        await dc.tell(down, dc.deploy_watch_activity("x" * 12, SELF_REPO, [1], ""))
        await dc.tell(None, dc.deploy_watch_activity("x" * 12, SELF_REPO, [1], ""))


async def _events(bus: EventBus) -> list:
    got: list = []

    async def keep(e):
        got.append(e)

    bus.subscribe_all(keep)
    return got


class TestInTheApiCycle:
    @pytest.fixture(autouse=True)
    def _hook(self):
        api_module.set_preflight(None)
        yield
        api_module.set_preflight(None)

    async def test_the_go_is_told_first_and_a_merge_to_the_swarm_s_main_starts_the_watch(self, monkeypatch):
        monkeypatch.setenv("SWARM_BUILD_SHA", "e39a13c" + "0" * 33)

        async def go():
            return d.preflight_of(_report(*FINE))

        api_module.set_preflight(go)
        bus = EventBus()
        events = await _events(bus)
        result = {"cost_usd": 1.0, "prs": [{"number": 318}], "merged_prs": [318], "held_prs": [], "date": "2026-10-08"}
        with patch("theswarm.cycle.run_daily_cycle", new=AsyncMock(return_value=result)):
            await api_module.run_api_cycle(cycle_id="abc123abc123", repo=SELF_REPO, description="Play", callback_url="",
                                           allowed_repos=[], event_bus=bus)
        devops = [e for e in events if isinstance(e, AgentActivity) and e.agent == "devops"]
        assert [e.action for e in devops] == ["preflight", "deploy_watch"]
        assert events.index(devops[0]) < next(i for i, e in enumerate(events) if isinstance(e, CycleCompleted))
        assert devops[1].metadata == {"merged": [318], "build_before": "e39a13c" + "0" * 33}

    async def test_no_watch_on_a_target_nor_without_a_merge_nor_without_devops(self, monkeypatch):
        async def go():
            return d.preflight_of(_report(*FINE))

        for repo, merged, hook in (("jrechet/concert-tour-app", [5], go), (SELF_REPO, [], go), (SELF_REPO, [5], None)):
            api_module.set_preflight(hook)
            bus = EventBus()
            events = await _events(bus)
            result = {"cost_usd": 1.0, "prs": [{"number": 5}], "merged_prs": merged, "held_prs": [], "date": "2026-10-08"}
            with patch("theswarm.cycle.run_daily_cycle", new=AsyncMock(return_value=result)):
                await api_module.run_api_cycle(cycle_id="abc123abc124", repo=repo, description="Play", callback_url="",
                                               allowed_repos=[], event_bus=bus)
            assert not [e for e in events if isinstance(e, AgentActivity) and e.action == "deploy_watch"], (repo, merged, hook)

    async def test_a_no_go_is_told_before_the_cycle_is_refused(self):
        from theswarm.api import CycleRequest, get_cycle_tracker

        record = get_cycle_tracker().create(CycleRequest(repo="o/r", description="Play"))

        async def no_go():
            return d.preflight_of(_report(d.Finding("claude", "Claude", "bad", "the weekly window is shut")))

        api_module.set_preflight(no_go)
        bus = AsyncMock()
        await api_module._run_api_cycle(record.id, "o/r", "Play", "", [], event_bus=bus, project_id="o/r")
        told = bus.publish.await_args_list[0].args[0]
        assert isinstance(told, AgentActivity) and told.action == "preflight_nogo" and str(told.cycle_id) == record.id
        assert "Claude: the weekly window is shut" in told.detail


@dataclass
class _Record:
    event_type: str
    payload: dict
    occurred_at: datetime = NOW


@dataclass
class _Store:
    by_cycle: dict = field(default_factory=dict)

    async def list_for_cycle(self, cycle_id):
        return list(self.by_cycle.get(cycle_id, []))

    def act(self, cycle_id, action, metadata=None):
        self.by_cycle.setdefault(cycle_id, []).append(
            _Record("AgentActivity", {"agent": "devops", "action": action, "metadata": metadata or {}}))


class _Cycles:
    def __init__(self, *cycles):
        self.cycles = list(cycles)

    async def list_since(self, since, limit=5000):
        return [c for c in self.cycles if c.started_at >= since]


def _cycle(cid, merged=(318,), status=CycleStatus.COMPLETED, hours_ago=1):
    return Cycle(id=CycleId(cid), project_id=SELF_REPO, status=status, triggered_by="web",
                 started_at=NOW - timedelta(hours=hours_ago), prs_merged=tuple(merged))


OLD, NEW = "e39a13c" + "0" * 33, "f00d123" + "0" * 33


class TestTheWatchIsClosed:
    def _rig(self, *cycles):
        store, told = _Store(), []

        async def publish(event):
            told.append(event)
            store.act(str(event.cycle_id), event.action, event.metadata)

        return store, told, publish, _Cycles(*cycles)

    async def test_landed_when_this_build_is_main_s_head_and_not_the_one_that_was_running(self):
        store, told, publish, cycles = self._rig(_cycle("aaaaaaaaaaaa"))
        store.act("aaaaaaaaaaaa", "deploy_watch", {"build_before": OLD})
        assert await dc.resolve_deploys(_report(main=OLD, build=OLD), cycles, store, publish, NOW) == []  # the old server, main not moved yet
        assert await dc.resolve_deploys(_report(main=NEW, build=OLD), cycles, store, publish, NOW) == []  # main moved, not here yet
        assert await dc.resolve_deploys(_report(main=NEW, build=NEW), cycles, store, publish, NOW) == ["aaaaaaaaaaaa"]
        assert told[0].action == "deploy_landed" and told[0].detail.startswith("The deploy landed: this server runs f00d123, main's head")
        assert await dc.resolve_deploys(_report(main=NEW, build=NEW), cycles, store, publish, NOW) == []  # once

    async def test_late_when_the_report_says_the_deploy_did_not_land_then_landed_later(self):
        store, told, publish, cycles = self._rig(_cycle("bbbbbbbbbbbb"))
        store.act("bbbbbbbbbbbb", "deploy_watch", {"build_before": OLD})
        late = d.Finding("deploy_watch", "Deploy watch", "bad", "main moved to f00d123 50 min ago and this box still runs e39a13c — the deploy did not land")
        assert await dc.resolve_deploys(_report(late, main=NEW, build=OLD), cycles, store, publish, NOW) == ["bbbbbbbbbbbb"]
        assert told[0].action == "deploy_late" and "the deploy did not land" in told[0].detail
        assert await dc.resolve_deploys(_report(late, main=NEW, build=OLD), cycles, store, publish, NOW) == []  # once
        assert await dc.resolve_deploys(_report(main=NEW, build=NEW), cycles, store, publish, NOW) == ["bbbbbbbbbbbb"]
        assert told[-1].action == "deploy_landed"

    async def test_only_watched_finished_merging_recent_cycles(self):
        store, told, publish, cycles = self._rig(
            _cycle("cccccccccccc"),  # no watch told
            _cycle("dddddddddddd", merged=()),
            _cycle("eeeeeeeeeeee", status=CycleStatus.FAILED),
            _cycle("ffffffffffff", hours_ago=72),
        )
        for cid in ("dddddddddddd", "eeeeeeeeeeee", "ffffffffffff"):
            store.act(cid, "deploy_watch", {"build_before": OLD})
        assert await dc.resolve_deploys(_report(main=NEW, build=NEW), cycles, store, publish, NOW) == []
        assert await dc.resolve_deploys(_report(main=NEW, build=NEW), None, store, publish, NOW) == []
        assert await dc.resolve_deploys(_report(main=NEW, build=NEW), cycles, None, publish, NOW) == []


class TestAQuickPreflight:
    """A Play waits for the preflight: it reads what stops a cycle, and nothing it measures."""

    async def test_the_light_read_skips_the_jobs_and_the_harness_and_reads_github_beside_the_hosts(self):
        import asyncio

        seen = {}

        async def github(repo):
            seen["github"] = asyncio.get_running_loop().time()
            await asyncio.sleep(0.05)
            return {"main_sha": "a" * 40, "runners": [{"name": "r", "status": "online", "busy": False}], "runs": []}

        async def host(h):
            seen["host"] = asyncio.get_running_loop().time()
            await asyncio.sleep(0.05)
            return {"slots": [], "disks": [], "load": None}

        async def harness(repo):
            raise AssertionError("the preflight does not read the harness")

        stack = {"hosts": [{"name": "jrec.fr", "ci_slot_dir": "/x"}], "ci": [{"repo": SELF_REPO}], "harness": {"repo": "o/t"}}
        started = asyncio.get_running_loop().time()
        report = await d.gather(stack, github=github, host_reader=host, claude=lambda: {"status": "ok"}, harness=harness,
                                build=lambda: "a" * 40, here=lambda: [], load=lambda: None, now=NOW, light=True)
        took = asyncio.get_running_loop().time() - started
        assert took < 0.09 and abs(seen["github"] - seen["host"]) < 0.04  # side by side, not one after the other
        keys = [f.key for f in report.findings]
        assert "harness" not in keys and "measures" not in keys and {"runners", "ci_slot", "claude", "disk_here"} <= set(keys)

    async def test_the_watch_s_preflight_reads_light_and_leaves_the_card_alone(self):
        from theswarm.application.services.ops_watch import OpsWatch

        full = _report(*FINE)
        light = _report(d.Finding("claude", "Claude", "bad", "the weekly window is shut"))

        async def gather():
            return full

        async def light_gather():
            return light

        watch = OpsWatch(gather, clock=lambda: NOW, preflight_gather=light_gather)
        await watch.refresh()
        answer = await watch.preflight()
        assert not answer.go and "Claude: the weekly window is shut" in answer.reasons
        assert watch.last() is full  # the card keeps its full report

    async def test_a_light_read_that_fails_falls_back_to_the_full_one(self):
        from theswarm.application.services.ops_watch import OpsWatch

        async def gather():
            return _report(*FINE)

        async def broken():
            raise RuntimeError("ssh timed out")

        assert (await OpsWatch(gather, clock=lambda: NOW, preflight_gather=broken).preflight()).go
