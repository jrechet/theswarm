"""The harness asks whether Claude answers before it opens an issue.

2026-09-30 07:22 UTC: the scheduled harness opened concert-tour-app#508
and started cycle 6e3d36ca7d1d, which died in 28 s on credentials dead
since 2026-09-28. /health said `claude: ok` — the auth wall lives ten
minutes in the process that ran into it, and nothing had called Claude
since the day before. `POST /api/claude/probe` asks: a standing wall
answers for free, else one short call on the cycles' own path does.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from theswarm.tools import auth_wall, claude_probe, quota_wall
from theswarm.tools.claude import ClaudeCLI, ClaudeResult, _CLIUnavailable

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPIRED = "SDK result success: Failed to authenticate: OAuth session expired and could not be refreshed"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")


def _cli(*outcomes):
    """A ClaudeCLI whose SDK answers `outcomes` in turn: a message raises
    it as the binary's failure, None answers OK."""
    cli = ClaudeCLI(model="haiku")
    calls: list[dict] = []

    async def run_sdk(prompt, **kw):
        calls.append({"prompt": prompt, **kw})
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if outcome is None:
            return ClaudeResult(text="OK", backend="sdk", cost_usd=0.0123)
        raise _CLIUnavailable(outcome)

    return cli, calls, patch.object(cli, "_run_sdk", side_effect=run_sdk)


async def test_dead_credentials_nobody_tried_today_are_found():
    cli, calls, sdk = _cli(EXPIRED)

    with sdk:
        answer = await claude_probe.probe(cli)

    assert answer["claude"] == "auth_expired" and answer["spent"] is True
    assert "OAuth session expired" in answer["claude_auth"]
    assert len(calls) == 1 and calls[0]["prompt"] == claude_probe.PROBE_PROMPT
    # The call raised the wall: /health says so from now on.
    assert auth_wall.wall_until() is not None


async def test_nothing_is_spent_against_a_standing_wall():
    auth_wall.raise_wall("Failed to authenticate: OAuth session expired")
    cli, calls, sdk = _cli(None)

    with sdk:
        answer = await claude_probe.probe(cli)

    assert calls == [] and answer["spent"] is False and answer["claude"] == "auth_expired"


async def test_a_closed_window_is_answered_with_when_it_reopens():
    quota_wall.raise_wall("You've hit your session limit · resets 4am (UTC)")
    cli, calls, sdk = _cli(None)

    with sdk:
        answer = await claude_probe.probe(cli)

    assert calls == [] and answer["claude"] == "quota_wall"
    assert answer["claude_quota_resets_at"] == quota_wall.wall_until().isoformat()


async def test_working_credentials_answer_ok():
    cli, calls, sdk = _cli(None)

    with sdk:
        answer = await claude_probe.probe(cli)

    assert answer["claude"] == "ok" and answer["spent"] is True
    assert answer["backend"] == "sdk" and answer["cost_usd"] == 0.0123
    assert "claude_auth" not in answer and "claude_quota_resets_at" not in answer


async def test_the_token_is_retried_without_like_a_cycle_would(monkeypatch):
    """The cycles' own path: a dead token, a live session on disk — ok."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-dead")
    cli, calls, sdk = _cli("SDK result success: Failed to authenticate: 401 invalid token", None)

    with sdk:
        answer = await claude_probe.probe(cli)

    assert answer["claude"] == "ok" and len(calls) == 2
    assert calls[1].get("drop_oauth_env") is True


async def test_the_answer_is_kept_a_minute():
    cli, calls, sdk = _cli(None)
    start = datetime(2026, 9, 30, 7, 20, tzinfo=timezone.utc)

    with sdk:
        first = await claude_probe.probe(cli, now=start)
        again = await claude_probe.probe(cli, now=start + timedelta(seconds=30))
        later = await claude_probe.probe(cli, now=start + claude_probe.KEEP + timedelta(seconds=1))

    assert len(calls) == 2
    assert first["spent"] is True and again["spent"] is False and later["spent"] is True
    assert again["claude"] == "ok"


async def test_probes_side_by_side_make_one_call():
    cli, calls, sdk = _cli(None)

    with sdk:
        answers = await asyncio.gather(*(claude_probe.probe(cli) for _ in range(3)))

    assert len(calls) == 1 and {a["claude"] for a in answers} == {"ok"}


async def test_a_probe_that_hangs_is_an_error_not_a_wall(monkeypatch):
    monkeypatch.setattr(claude_probe, "PROBE_BUDGET_SECONDS", 0.05)
    cli = ClaudeCLI(model="haiku")

    async def hang(prompt, **kw):
        await asyncio.sleep(5)

    with patch.object(cli, "run", side_effect=hang):
        answer = await claude_probe.probe(cli)

    assert answer["claude"] == "error" and "no answer" in answer["detail"]
    assert auth_wall.wall_until() is None and quota_wall.wall_until() is None


async def test_another_failure_is_an_error_the_harness_goes_past():
    cli, _, sdk = _cli("SDK result error: overloaded")

    with sdk:
        answer = await claude_probe.probe(cli)

    assert answer["claude"] == "error" and "overloaded" in answer["detail"]


# ── the route ───────────────────────────────────────────────────────


async def test_the_route_answers_the_probe():
    from theswarm.presentation.web.routes import api as api_routes

    app = FastAPI()
    app.include_router(api_routes.router)
    auth_wall.raise_wall("Failed to authenticate: OAuth session expired")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/claude/probe")

    assert response.status_code == 200
    assert response.json()["claude"] == "auth_expired" and response.json()["spent"] is False


# ── the harness ─────────────────────────────────────────────────────


def _harness():
    spec = importlib.util.spec_from_file_location("cycle_e2e_probe", ROOT / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _never(*_a, **_k):
    raise AssertionError("an issue was created with dead credentials")


def test_the_harness_asks_before_opening_an_issue(monkeypatch, tmp_path, capsys):
    """/health says ok — nothing ran into the wall today — and the probe
    finds the credentials dead: no issue, no cycle, nothing scored."""
    harness = _harness()
    asked: list[tuple] = []

    def api(path, payload=None):
        asked.append((path, payload))
        if path == "/api/claude/probe":
            return 200, {"claude": "auth_expired", "spent": True,
                         "claude_auth": "Failed to authenticate: OAuth session expired",
                         "detail": "Failed to authenticate: OAuth session expired"}
        return 200, {"status": "ok", "checks": {"claude": "ok"}}

    monkeypatch.setattr(harness, "_api", api)
    monkeypatch.setattr(harness, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(harness, "create_issue", _never)
    monkeypatch.setattr(harness, "start_cycle", _never)
    history = tmp_path / "runs.jsonl"

    ok, record = harness.run_one("jrechet/concert-tour-app", "Take an act off a lineup", None, 60, history)

    out = capsys.readouterr().out
    assert ok is True and record == {} and not history.exists()
    assert ("/api/claude/probe", {}) in asked
    assert "claude     : auth_expired (one call)" in out
    assert "NOT MEASURED" in out and "OAuth session expired" in out


def test_the_harness_waits_for_a_window_the_probe_names(monkeypatch, tmp_path, capsys):
    harness = _harness()
    monkeypatch.setattr(harness, "_api", lambda path, payload=None: (200, {
        "claude": "quota_wall", "spent": False, "claude_quota_resets_at": "2026-09-30T12:00:00+00:00"}))
    monkeypatch.setattr(harness, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(harness, "create_issue", _never)

    ok, record = harness.run_one("o/r", "Anything", None, 60, tmp_path / "runs.jsonl")

    assert ok is True and record == {}
    assert "closed until 2026-09-30T12:00:00+00:00" in capsys.readouterr().out


def test_a_server_without_the_probe_is_read_off_health(monkeypatch, tmp_path, capsys):
    harness = _harness()

    def api(path, payload=None):
        if path == "/api/claude/probe":
            return 404, {"detail": "Not Found"}
        return 200, {"checks": {"claude": "auth_expired"}, "claude_auth": "OAuth session expired"}

    monkeypatch.setattr(harness, "_api", api)
    monkeypatch.setattr(harness, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(harness, "create_issue", _never)

    ok, record = harness.run_one("o/r", "Anything", None, 60, tmp_path / "runs.jsonl")

    out = capsys.readouterr().out
    assert ok is True and record == {} and "NOT MEASURED" in out
    assert "claude     :" not in out


def test_an_answer_that_is_not_a_wall_lets_the_run_go_on(monkeypatch):
    harness = _harness()

    assert harness.claude_answer(api=lambda p, payload=None: (200, {"claude": "ok", "spent": True})) \
        == {"claude": "ok", "spent": True}
    assert harness.claude_answer(api=lambda p, payload=None: (0, {"error": "unreachable"})) == {}
    assert harness.claude_answer(api=lambda p, payload=None: (401, {"detail": "no key"})) == {}
