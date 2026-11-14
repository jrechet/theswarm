"""A closed Claude subscription window is waited out, not died of (A1).

2026-11-11: three cycles ran side by side on prod, the session window
closed under them ("You've hit your session limit · resets 1:10pm (UTC)"),
and all three ended `failed` after eight minutes — the third without
starting, its preflight refusing. The window reopens on its own at a time
the message names: the cycle waits for it, says so, and goes on from its
last finished node on its own graph thread. A wall too far away (a weekly
limit) and dead credentials still end the cycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm import claude_window
from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker, run_api_cycle
from theswarm.tools import quota_wall
from theswarm.tools.claude import ClaudeFatalError

RESULT = {"cost_usd": 1.0, "prs": [], "reviews": [], "date": "2026-11-14"}


@pytest.fixture(autouse=True)
def _clean():
    from theswarm.dashboard import get_dashboard_state

    quota_wall.clear()
    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    dash = get_dashboard_state()
    cost = dash.cost_so_far
    yield
    quota_wall.clear()
    tracker._cycles.clear()
    tracker._cycles.update(before)
    dash.cost_so_far = cost  # the runner writes the process-wide dashboard; leave it as found


class _Clock:
    """Sleeping moves the clock; the wall falls when its time comes."""

    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.slept: list[float] = []
        self.seen_waiting: list[str] = []

    async def sleep(self, seconds: float) -> None:
        record = get_cycle_tracker().get(self.cycle_id)
        self.seen_waiting.append(getattr(record, "waiting", ""))
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)
        quota_wall.wall_until(self.now)  # a passed wall clears

    def __call__(self) -> datetime:
        return self.now


def _start(cycle_id: str) -> None:
    record = get_cycle_tracker().create(CycleRequest(repo="owner/app", description="t", issue_number=7))
    get_cycle_tracker()._cycles[cycle_id] = record.model_copy(update={"id": cycle_id})


async def _run(cycle_id: str, daily, clock: _Clock, **kwargs):
    clock.cycle_id = cycle_id
    _start(cycle_id)
    with patch("theswarm.cycle.run_daily_cycle", new=daily), \
         patch.object(claude_window, "sleep", clock.sleep), patch.object(claude_window, "utcnow", clock):
        await run_api_cycle(cycle_id, "owner/app", "t", "", [], issue_number=7, **kwargs)
    return get_cycle_tracker().get(cycle_id)


def _closes_the_window(clock: _Clock, after: timedelta):
    async def fail(*args, **kwargs):
        quota_wall.raise_wall("You've hit your session limit", now=clock.now)  # 30 min when no time is named
        quota_wall._until = clock.now + after
        raise ClaudeFatalError("Claude subscription exhausted: You've hit your session limit")
    return fail


async def test_the_cycle_waits_for_the_window_and_goes_on_from_where_it_stopped():
    clock = _Clock()
    calls: list[dict] = []
    fail = _closes_the_window(clock, timedelta(hours=2))

    async def daily(config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            await fail()
        return RESULT

    record = await _run("waitwaitwait", daily, clock)
    assert record.status == CycleStatus.COMPLETED and record.waiting == ""
    assert len(calls) == 2 and calls[1]["resume"] is True and calls[1]["cycle_id"] == "waitwaitwait"
    assert calls[0]["resume"] is False
    assert sum(clock.slept) >= 2 * 3600  # waited the wall out, plus a margin
    assert any("Claude" in w and "until" in w for w in clock.seen_waiting)  # said while it waited


async def test_a_continuation_waits_on_its_origin_s_thread():
    clock = _Clock()
    calls: list[dict] = []
    fail = _closes_the_window(clock, timedelta(minutes=40))

    async def daily(config, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            await fail()
        return RESULT

    await _run("contcontcont", daily, clock, resume_cycle_id="originorigin")
    assert [c["cycle_id"] for c in calls] == ["originorigin", "originorigin"] and all(c["resume"] for c in calls)


async def test_a_wall_too_far_away_ends_the_cycle_as_before():
    clock = _Clock()
    daily = AsyncMock(side_effect=_closes_the_window(clock, timedelta(days=3)))  # a weekly limit
    record = await _run("weekweekweek", daily, clock)
    assert record.status == CycleStatus.FAILED and record.error.startswith("ClaudeFatalError")
    assert daily.await_count == 1 and clock.slept == []


async def test_dead_credentials_are_not_waited_for():
    clock = _Clock()
    daily = AsyncMock(side_effect=ClaudeFatalError("Claude credentials expired: OAuth session expired"))
    record = await _run("authauthauth", daily, clock)
    assert record.status == CycleStatus.FAILED and daily.await_count == 1 and clock.slept == []


async def test_a_preflight_refused_only_on_the_window_waits_then_starts():
    from theswarm import api
    from theswarm.agents.devops import Finding

    clock = _Clock()
    quota_wall._until = clock.now + timedelta(minutes=50)
    closed = Finding("claude", "Claude", "bad", "subscription window closed until 13:10 UTC")

    async def preflight():
        if quota_wall.wall_until(clock.now) is not None:
            return SimpleNamespace(go=False, reasons=("Claude: subscription window closed",),
                                   report=SimpleNamespace(findings=(closed,)))
        return SimpleNamespace(go=True, reasons=(), report=SimpleNamespace(findings=()))

    daily = AsyncMock(return_value=RESULT)
    with patch.object(api, "_PREFLIGHT", preflight):
        record = await _run("prefprefpref", daily, clock)
    assert record.status == CycleStatus.COMPLETED and daily.await_count == 1
    assert sum(clock.slept) >= 50 * 60


async def test_a_preflight_refused_for_anything_else_still_refuses():
    from theswarm import api
    from theswarm.agents.devops import Finding

    clock = _Clock()
    quota_wall._until = clock.now + timedelta(minutes=50)
    findings = (Finding("claude", "Claude", "bad", "window closed"), Finding("disk_here", "Disk (here)", "bad", "99% used"))

    async def preflight():
        return SimpleNamespace(go=False, reasons=("Claude: closed", "Disk (here): 99% used"),
                               report=SimpleNamespace(findings=findings))

    daily = AsyncMock(return_value=RESULT)
    with patch.object(api, "_PREFLIGHT", preflight):
        record = await _run("diskdiskdisk", daily, clock)
    assert record.status == CycleStatus.FAILED and record.error.startswith("preflight:") and daily.await_count == 0


def test_how_long_is_worth_waiting():
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    assert claude_window.worth_waiting(now + timedelta(hours=4), timedelta(0), now=now)
    assert not claude_window.worth_waiting(now + timedelta(days=2), timedelta(0), now=now)
    assert not claude_window.worth_waiting(now + timedelta(hours=2), timedelta(hours=5), now=now)  # waited enough already
    assert not claude_window.worth_waiting(None, timedelta(0), now=now)


def test_the_api_says_a_cycle_waits():
    from theswarm.presentation.web.routes.api import _tracker_record_to_unified_json

    _start("apiwaitapiwa")
    get_cycle_tracker().set_waiting("apiwaitapiwa", "Claude's subscription window is closed until 13:10 UTC")
    assert "13:10" in _tracker_record_to_unified_json(get_cycle_tracker().get("apiwaitapiwa"))["waiting"]
