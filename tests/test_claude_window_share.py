"""The swarm's share of Claude's window (A1).

Every Claude call streams a `RateLimitEvent`; on the owner's account
(2026-11-14) its `utilization` was None and the numbers were in
`raw["unifiedWindows"]` — 5-hour at 5 %, weekly at 66 %. The code threw the
event away. The owner's own Claude Code draws on the same window: past the
share he sets (Settings → Cycles), the swarm makes no call until the window
resets, a cycle waits as it does for a closed window, and the harness starts
nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from claude_agent_sdk import RateLimitEvent, RateLimitInfo, ResultMessage, SystemMessage

from theswarm import claude_window
from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI, ClaudeFatalError

NOW = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)


def _info(five_hour: float, weekly: float = 0.10, *, now: datetime = NOW) -> RateLimitInfo:
    """What the CLI sent on 2026-11-14, numbers swapped."""
    five_resets = int((now + timedelta(hours=2)).timestamp())
    week_resets = int((now + timedelta(days=3)).timestamp())
    return RateLimitInfo(status="allowed", resets_at=five_resets, rate_limit_type="five_hour", utilization=None,
                         raw={"status": "allowed", "rateLimitType": "five_hour", "resetsAt": five_resets,
                              "unifiedWindows": {"five_hour": {"utilization": five_hour, "resetsAt": five_resets},
                                                 "seven_day": {"utilization": weekly, "resetsAt": week_resets}}})


@pytest.fixture
def share(monkeypatch):
    def _set(percent: int | None):
        if percent is None:
            monkeypatch.delenv("SWARM_CLAUDE_WINDOW_SHARE", raising=False)
        else:
            monkeypatch.setenv("SWARM_CLAUDE_WINDOW_SHARE", str(percent))
    return _set


def test_the_windows_are_read_off_the_unified_numbers():
    claude_window.note(_info(0.05, 0.66), now=NOW)
    rows = {w["name"]: w for w in claude_window.windows(now=NOW)}
    assert rows["five_hour"]["utilization"] == pytest.approx(0.05)
    assert rows["seven_day"]["utilization"] == pytest.approx(0.66) and rows["seven_day"]["label"] == "weekly"
    assert claude_window.windows(now=NOW)[0]["name"] == "seven_day"  # the fullest first
    # a window past its reset is no longer known
    assert {w["name"] for w in claude_window.windows(now=NOW + timedelta(hours=3))} == {"seven_day"}


def test_a_reading_never_raises():
    claude_window.note(None)
    claude_window.note(SimpleNamespace(raw={"unifiedWindows": {"five_hour": {"utilization": "x"}}}))
    claude_window.note(SimpleNamespace(raw=None, rate_limit_type="five_hour", utilization=0.4, resets_at=None))
    assert [w["name"] for w in claude_window.windows()] == ["five_hour"]


def test_all_of_the_window_by_default(share):
    share(None)
    claude_window.note(_info(0.99), now=NOW)
    assert claude_window.share() == 100 and claude_window.over_share(now=NOW) is None


def test_past_the_share_the_swarm_waits_for_the_reset(share, monkeypatch):
    share(80)
    claude_window.note(_info(0.82), now=NOW)
    monkeypatch.setattr(claude_window, "utcnow", lambda: NOW)
    over = claude_window.over_share(now=NOW)
    assert over["name"] == "five_hour" and over["share"] == 80
    assert claude_window.closed_until() == NOW + timedelta(hours=2)
    assert "5-hour window is at 82%, the swarm's share is 80%" in claude_window.words(claude_window.closed_until())
    assert claude_window.worth_waiting(claude_window.closed_until(), timedelta(0), now=NOW)


def test_the_share_is_bounded(share):
    share(3)
    assert claude_window.share() == claude_window.MIN_SHARE
    share(250)
    assert claude_window.share() == 100


async def test_a_call_over_the_share_is_not_made(share, monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    share(50)
    claude_window.note(_info(0.6, now=datetime.now(timezone.utc)))
    made: list[str] = []

    def never(prompt, options):
        made.append(prompt)
        raise AssertionError("no call over the share")

    monkeypatch.setattr(claude_mod, "_sdk_query", never)
    with pytest.raises(ClaudeFatalError, match="swarm's share is 50%"):
        await ClaudeCLI(model="haiku").run("hi")
    assert made == []


async def test_every_call_keeps_what_the_rate_limit_event_says(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    now = datetime.now(timezone.utc)

    async def stream(prompt, options):
        yield SystemMessage(subtype="init", data={"apiKeySource": "none", "session_id": "s-1"})
        yield RateLimitEvent(rate_limit_info=_info(0.31, 0.7, now=now), uuid="u", session_id="s-1")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="s-1", total_cost_usd=0.0, usage={}, result="ok")

    monkeypatch.setattr(claude_mod, "_sdk_query", stream)
    await ClaudeCLI(model="haiku").run("hi")
    assert {w["name"]: round(w["utilization"], 2) for w in claude_window.windows()} == {"five_hour": 0.31, "seven_day": 0.7}


def test_health_the_rail_devops_and_the_probe_say_it(share):
    from theswarm.agents.devops import BAD, claude_finding
    from theswarm.presentation.web.shell import claude_status
    from theswarm.tools.claude_probe import standing_wall

    share(50)
    claude_window.note(_info(0.6, now=datetime.now(timezone.utc)))
    status = claude_status()
    assert status["status"] == "over_share" and status["detail"].startswith("until ")
    assert claude_finding(status).status == BAD  # the preflight: a cycle waits, as for a wall
    wall = standing_wall()
    assert wall["claude"] == "over_share" and wall["claude_quota_resets_at"]  # the harness starts nothing


async def test_the_owner_sets_the_share_in_settings_cycles(tmp_path):
    from theswarm.application.services.cycle_limits import CycleLimitsError, CycleLimitsService
    from theswarm.cycle_gate import set_cycle_limits

    class Rows:
        def __init__(self):
            self.rows: dict[str, int] = {}

        async def all(self):
            return dict(self.rows)

        async def put(self, scope, value, by=""):
            if value is None:
                self.rows.pop(scope, None)
            else:
                self.rows[scope] = value

    rows = Rows()
    service = CycleLimitsService(rows)
    try:
        await service.save(None, {}, claude_share=70)
        assert rows.rows == {"claude:share": 70} and claude_window.share() == 70
        await service.save(None, {})  # left out: kept
        assert claude_window.share() == 70
        await service.save(None, {}, claude_share=100)  # all of it: no row
        assert rows.rows == {} and claude_window.share() == 100
        with pytest.raises(CycleLimitsError):
            await service.save(None, {}, claude_share=5)
    finally:
        set_cycle_limits(None)


async def test_all_of_it_in_settings_beats_a_share_in_the_environment(share):
    from theswarm.application.services.cycle_limits import CycleLimitsService
    from theswarm.cycle_gate import set_cycle_limits

    class Rows:
        rows: dict = {}

        async def all(self):
            return dict(self.rows)

        async def put(self, scope, value, by=""):
            self.rows = {**self.rows, scope: value} if value is not None else {
                k: v for k, v in self.rows.items() if k != scope}

    share(80)
    service = CycleLimitsService(Rows())
    try:
        await service.save(None, {}, claude_share=100)
        assert claude_window.share() == 100  # the owner's word, not the instance's 80
        await service.save(None, {}, claude_share=80)
        assert claude_window.share() == 80 and service.claude_share() is None  # the default: no row
    finally:
        set_cycle_limits(None)
