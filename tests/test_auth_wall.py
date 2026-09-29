"""Expired Claude credentials are a wall, not a failure of the swarm.

2026-09-29 13:47 UTC: prod came back from a two-day outage with its mounted
~/.claude session dead. The harness's cycle (3ce3b63ab59a) died in 26 s on
"Failed to authenticate: OAuth session expired and could not be refreshed",
was scored a failed run and a REGRESSION, and tried to alert. Nothing about
the swarm was measured; a person has to renew the credentials. Like the
subscription window: fatal (`ClaudeFatalError` → the eval's
`interrupted`), remembered so no call is spent against it, on /health as
`claude: auth_expired`, and the harness starts nothing while it stands.
Not persisted: a redeploy is how new credentials arrive.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from theswarm import evals
from theswarm.tools import auth_wall
from theswarm.tools.claude import ClaudeCLI, ClaudeFatalError, _CLIUnavailable

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXPIRED = "SDK result success: Failed to authenticate: OAuth session expired and could not be refreshed"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)


def _failing(*messages):
    calls = []

    async def run(prompt, **kw):
        calls.append(kw)
        message = messages[min(len(calls), len(messages)) - 1]
        if message is None:
            from theswarm.tools.claude import ClaudeResult
            return ClaudeResult(text="ok")
        raise _CLIUnavailable(message)

    return run, calls


async def test_expired_credentials_are_fatal_and_say_how_to_renew():
    cli = ClaudeCLI(model="haiku")
    run, _ = _failing(EXPIRED)

    with patch.object(cli, "_run_sdk", side_effect=run):
        with pytest.raises(ClaudeFatalError, match="credentials expired") as raised:
            await cli.run("hi")

    assert "claude setup-token" in str(raised.value)
    assert auth_wall.wall_until() is not None


async def test_no_call_is_spent_while_the_wall_stands():
    auth_wall.raise_wall(EXPIRED)
    cli = ClaudeCLI(model="haiku")
    run, calls = _failing("unused")

    with patch.object(cli, "_run_sdk", side_effect=run):
        with pytest.raises(ClaudeFatalError, match="no call made"):
            await cli.run("hi")

    assert calls == []


async def test_the_wall_is_tried_again_after_a_while():
    auth_wall.raise_wall(EXPIRED, now=datetime.now(timezone.utc) - auth_wall.HOLD - timedelta(seconds=1))
    cli = ClaudeCLI(model="haiku")
    run, calls = _failing(None)

    with patch.object(cli, "_run_sdk", side_effect=run):
        result = await cli.run("hi")

    assert result.text == "ok" and len(calls) == 1  # someone logged in again


async def test_with_the_env_token_the_retry_without_it_decides(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-test")
    cli = ClaudeCLI(model="haiku")

    run, calls = _failing(EXPIRED, None)
    with patch.object(cli, "_run_sdk", side_effect=run):
        assert (await cli.run("hi")).text == "ok"  # the mounted session still works
    assert calls[1].get("drop_oauth_env") is True and auth_wall.wall_until() is None

    run, _ = _failing(EXPIRED, EXPIRED)
    with patch.object(cli, "_run_sdk", side_effect=run):
        with pytest.raises(ClaudeFatalError, match="credentials expired"):
            await cli.run("hi")


@pytest.mark.parametrize("message", [
    "exit 1: connection reset by peer",
    "SDK result error: GitHub answered 401 on the PR comment",  # not our credentials
    "JSON parse failed",
])
async def test_other_failures_stay_a_failed_call(message):
    cli = ClaudeCLI(model="haiku")
    run, _ = _failing(message)

    with patch.object(cli, "_run_sdk", side_effect=run):
        with pytest.raises(RuntimeError) as raised:
            await cli.run("hi")

    assert not isinstance(raised.value, ClaudeFatalError)
    assert auth_wall.wall_until() is None


def test_the_eval_does_not_score_it():
    error = "ClaudeFatalError: Claude credentials expired: Failed to authenticate — renew them"

    record = evals.score(None, evals.Observed(state="failed", error=error))

    assert record["outcome"] == evals.OUTCOME_INTERRUPTED and not evals.is_measured(record)


# ── /health and the harness ──────────────────────────────────────────


def _app() -> FastAPI:
    from theswarm.presentation.web.routes import health as health_routes

    app = FastAPI()
    app.include_router(health_routes.router)
    app.state.project_repo = None
    app.state.sse_hub = object()
    app.state.gateway_bridge = None
    return app


async def test_health_says_the_credentials_expired_and_stays_alive():
    auth_wall.raise_wall(EXPIRED)

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["claude"] == "auth_expired" and body["status"] == "warn"
    assert "OAuth session expired" in body["claude_auth"]


def _harness():
    spec = importlib.util.spec_from_file_location("cycle_e2e_auth", ROOT / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_harness_reads_it_off_health():
    harness = _harness()

    assert harness.credentials_expired(api=lambda p: (200, {"checks": {"claude": "auth_expired"},
                                                            "claude_auth": "OAuth session expired"})) \
        == "OAuth session expired"
    assert harness.credentials_expired(api=lambda p: (200, {"checks": {"claude": "ok"}})) == ""
    assert harness.credentials_expired(api=lambda p: (0, {"error": "unreachable"})) == ""


def test_the_harness_starts_nothing_while_it_stands(monkeypatch, tmp_path, capsys):
    harness = _harness()
    monkeypatch.setattr(harness, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(harness, "quota_wall_until", lambda **k: "")
    monkeypatch.setattr(harness, "credentials_expired", lambda **k: "OAuth session expired")

    def never(*_a, **_k):
        raise AssertionError("an issue was created with dead credentials")

    monkeypatch.setattr(harness, "create_issue", never)
    monkeypatch.setattr(harness, "start_cycle", never)
    history = tmp_path / "runs.jsonl"

    ok, record = harness.run_one("jrechet/concert-tour-app", "Hide past concerts", None, 60, history)

    out = capsys.readouterr().out
    assert ok is True and record == {} and not history.exists()
    assert "NOT MEASURED" in out and "credentials" in out
