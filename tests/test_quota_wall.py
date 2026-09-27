"""A closed subscription window is remembered until it reopens.

The prod container shares the Claude subscription with the owner's own
Claude Code. When the window ran out on 2026-09-27 ("You've hit your weekly
limit · resets Sep 29, 4am (UTC)"), the daily harness still created its
story issue on the target, started a cycle, and the cycle died in 51 s on
the first call — as had three cycles at 12:40 two days before. Every call
until the reset is a call against a wall: the wall is now remembered in
the process, `/health` says when it lifts, the wrapper refuses to spend a
call before then, and the harness starts nothing.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from theswarm.tools import quota_wall
from theswarm.tools.claude import ClaudeCLI, ClaudeFatalError, _CLIUnavailable

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOW = datetime(2026, 9, 27, 7, 15, tzinfo=timezone.utc)
WEEKLY = "SDK result success: You've hit your weekly limit · resets Sep 29, 4am (UTC)"
SESSION = "exit 1: You've hit your session limit · resets 1:20pm (UTC)"


@pytest.fixture(autouse=True)
def _no_api_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)


# ── The reset time ─────────────────────────────────────────────────────


@pytest.mark.parametrize("message, expected", [
    (WEEKLY, datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)),
    (SESSION, datetime(2026, 9, 27, 13, 20, tzinfo=timezone.utc)),
    ("You've hit your session limit · resets 9:50am (UTC)", datetime(2026, 9, 27, 9, 50, tzinfo=timezone.utc)),
    ("resets Sep 29, 4:05pm (UTC)", datetime(2026, 9, 29, 16, 5, tzinfo=timezone.utc)),
])
def test_the_reset_time_is_read_off_the_message(message, expected):
    assert quota_wall.reset_time_of(message, now=NOW) == expected


def test_a_time_already_past_today_is_tomorrow():
    later = NOW.replace(hour=14)

    assert quota_wall.reset_time_of(SESSION, now=later) == datetime(2026, 9, 28, 13, 20, tzinfo=timezone.utc)


def test_a_date_already_past_this_year_is_next_year():
    december = datetime(2026, 12, 30, tzinfo=timezone.utc)

    assert quota_wall.reset_time_of("resets Jan 2, 4am (UTC)", now=december) == datetime(2027, 1, 2, 4, 0, tzinfo=timezone.utc)


def test_a_message_without_a_reset_time_has_none():
    assert quota_wall.reset_time_of("usage limit reached", now=NOW) is None


# ── The wall ───────────────────────────────────────────────────────────


def test_a_raised_wall_stands_until_its_reset():
    quota_wall.raise_wall(WEEKLY, now=NOW)

    assert quota_wall.wall_until(now=NOW) == datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)
    assert quota_wall.reason() == WEEKLY
    assert quota_wall.wall_until(now=datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)) is None
    assert quota_wall.reason() == ""


def test_a_wall_without_a_reset_time_holds_briefly():
    quota_wall.raise_wall("usage limit reached", now=NOW)

    assert quota_wall.wall_until(now=NOW) == NOW + quota_wall.DEFAULT_HOLD


def test_a_later_reset_replaces_an_earlier_one_never_the_reverse():
    quota_wall.raise_wall(SESSION, now=NOW)
    quota_wall.raise_wall(WEEKLY, now=NOW)
    quota_wall.raise_wall(SESSION, now=NOW)

    assert quota_wall.wall_until(now=NOW) == datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)


# ── The wrapper ────────────────────────────────────────────────────────


async def test_a_quota_failure_raises_the_wall():
    cli = ClaudeCLI(model="haiku")

    async def out_of_quota(prompt, **_kw):
        raise _CLIUnavailable(SESSION)

    with patch.object(cli, "_run_sdk", side_effect=out_of_quota):
        with pytest.raises(ClaudeFatalError):
            await cli.run("hi")

    assert quota_wall.wall_until() is not None


async def test_no_call_is_spent_while_the_wall_stands():
    quota_wall.raise_wall(WEEKLY, now=datetime.now(timezone.utc))
    cli = ClaudeCLI(model="haiku")
    attempts = 0

    async def counting(prompt, **_kw):
        nonlocal attempts
        attempts += 1

    with patch.object(cli, "_run_sdk", side_effect=counting):
        with pytest.raises(ClaudeFatalError, match="Sep 29"):
            await cli.run("hi")

    assert attempts == 0


async def test_calls_go_through_again_once_the_wall_has_passed():
    quota_wall.raise_wall(SESSION, now=datetime.now(timezone.utc) - timedelta(days=2))
    cli = ClaudeCLI(model="haiku")
    attempts = 0

    async def counting(prompt, **_kw):
        nonlocal attempts
        attempts += 1
        raise _CLIUnavailable("something else")

    with patch.object(cli, "_run_sdk", side_effect=counting):
        with pytest.raises(RuntimeError):
            await cli.run("hi")

    assert attempts == 1


# ── /health ────────────────────────────────────────────────────────────


def _app() -> FastAPI:
    from theswarm.presentation.web.routes import health as health_routes

    app = FastAPI()
    app.include_router(health_routes.router)
    app.state.project_repo = None
    app.state.sse_hub = object()
    app.state.gateway_bridge = None
    return app


async def _health() -> tuple[int, dict]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/health")
    return response.status_code, response.json()


async def test_health_says_the_window_is_open():
    status, body = await _health()

    assert status == 200
    assert body["checks"]["claude"] == "ok"
    assert "claude_quota_resets_at" not in body


async def test_health_says_when_the_window_reopens_and_stays_alive():
    quota_wall.raise_wall(WEEKLY, now=datetime.now(timezone.utc))

    status, body = await _health()

    assert status == 200  # a closed window is not a dead container
    assert body["checks"]["claude"] == "quota_wall"
    assert body["claude_quota_resets_at"] == "2026-09-29T04:00:00+00:00"


# ── The harness ────────────────────────────────────────────────────────


def _harness():
    spec = importlib.util.spec_from_file_location("cycle_e2e_wall", ROOT / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_harness_reads_the_reset_off_health():
    harness = _harness()

    assert harness.quota_wall_until(api=lambda p: (200, {"claude_quota_resets_at": "2026-09-29T04:00:00+00:00"})) == "2026-09-29T04:00:00+00:00"
    assert harness.quota_wall_until(api=lambda p: (200, {"status": "ok"})) == ""
    assert harness.quota_wall_until(api=lambda p: (0, {"error": "unreachable"})) == ""


def test_the_harness_starts_nothing_while_the_wall_stands(monkeypatch, tmp_path, capsys):
    harness = _harness()
    monkeypatch.setattr(harness, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(harness, "quota_wall_until", lambda **k: "2026-09-29T04:00:00+00:00")

    def never(*_a, **_k):
        raise AssertionError("an issue was created against a closed window")

    monkeypatch.setattr(harness, "create_issue", never)
    monkeypatch.setattr(harness, "start_cycle", never)
    history = tmp_path / "runs.jsonl"

    ok, record = harness.run_one("jrechet/concert-tour-app", "Hide past concerts", None, 60, history)

    assert ok is True and record == {}
    assert "NOT MEASURED" in capsys.readouterr().out
    assert not history.exists()
