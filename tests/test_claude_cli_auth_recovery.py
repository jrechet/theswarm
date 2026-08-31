"""A stale env token must not shadow a working session, and must say so.

Prod, twice: every Claude call failed with `RuntimeError: Claude CLI failed
twice … exit 1:` — an empty message, because the CLI reports failures as a
JSON envelope on *stdout* and leaves stderr empty. Behind it,
`CLAUDE_CODE_OAUTH_TOKEN` (expired) outranked `~/.claude`, whose credentials
were valid and self-refreshing: unset the variable and the same call
succeeded.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools.claude import (
    ClaudeCLI,
    ClaudeResult,
    _CLIUnavailable,
    _envelope_error,
    _is_auth_failure,
)


# ── The CLI's real error lives on stdout ───────────────────────────────


def test_envelope_error_reads_the_json_on_stdout():
    stdout = b'{"is_error":true,"result":"OAuth access token has expired."}'
    assert _envelope_error(stdout) == "OAuth access token has expired."


def test_envelope_error_falls_back_to_the_status_code():
    assert _envelope_error(b'{"is_error":true,"api_error_status":401}') == "401"


def test_envelope_error_tolerates_junk():
    assert _envelope_error(b"not json") == ""
    assert _envelope_error(b"[1,2,3]") == ""
    assert _envelope_error(b"") == ""


async def test_nonzero_exit_reports_the_stdout_message(monkeypatch):
    """The bug: an empty stderr produced a bare 'exit 1:' and hid the cause."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "cli")

    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate = AsyncMock(return_value=(
        b'{"is_error":true,"result":"OAuth access token has expired."}', b"",
    ))

    with patch("theswarm.tools.claude.shutil.which", return_value="/usr/bin/claude"), \
         patch("theswarm.tools.claude.asyncio.create_subprocess_exec",
               AsyncMock(return_value=proc)):
        with pytest.raises(RuntimeError, match="OAuth access token has expired"):
            await ClaudeCLI(model="haiku").run("hi")


# ── Auth-failure detection ─────────────────────────────────────────────


@pytest.mark.parametrize("message", [
    "exit 1: OAuth access token has expired.",
    "exit 1: Failed to authenticate. API Error: 401",
    "exit 1: Not logged in · Please run /login",
    "CLI reported error: invalid API key",
])
def test_auth_failures_are_recognised(message):
    assert _is_auth_failure(_CLIUnavailable(message)) is True


@pytest.mark.parametrize("message", [
    "exit 1: connection reset by peer",
    "CLI timed out after 180s",
    "JSON parse failed",
])
def test_transient_failures_are_not_auth_failures(message):
    assert _is_auth_failure(_CLIUnavailable(message)) is False


# ── Recovery: drop the env override and retry ──────────────────────────


async def test_auth_failure_retries_without_the_env_token(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    calls: list[bool] = []

    async def flaky(prompt, *, workdir, timeout, drop_oauth_env=False):
        calls.append(drop_oauth_env)
        if not drop_oauth_env:
            raise _CLIUnavailable("exit 1: OAuth access token has expired.")
        return ClaudeResult(text="recovered", backend="cli")

    cli = ClaudeCLI(model="haiku")
    with patch.object(cli, "_run_cli", side_effect=flaky):
        result = await cli.run("hi")

    assert result.text == "recovered"
    assert calls == [False, True]  # first with the override, then without


async def test_transient_failure_does_not_drop_the_env_token(monkeypatch):
    """Only auth failures warrant discarding the configured credential."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fine")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    calls: list[bool] = []

    async def always_transient(prompt, *, workdir, timeout, drop_oauth_env=False):
        calls.append(drop_oauth_env)
        raise _CLIUnavailable("CLI timed out after 180s")

    cli = ClaudeCLI(model="haiku")
    with patch.object(cli, "_run_cli", side_effect=always_transient):
        with pytest.raises(RuntimeError):
            await cli.run("hi")

    # The plain retry runs, but never with the override dropped
    assert True not in calls


async def test_no_env_token_means_no_extra_attempt(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    calls: list[bool] = []

    async def failing(prompt, *, workdir, timeout, drop_oauth_env=False):
        calls.append(drop_oauth_env)
        raise _CLIUnavailable("exit 1: OAuth access token has expired.")

    cli = ClaudeCLI(model="haiku")
    with patch.object(cli, "_run_cli", side_effect=failing):
        with pytest.raises(RuntimeError):
            await cli.run("hi")

    assert True not in calls


async def test_dropping_the_override_removes_it_from_the_child_env(monkeypatch):
    """The retry must actually unset the variable for the subprocess."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "cli")

    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(
        b'{"is_error":false,"result":"ok","usage":{},"total_cost_usd":0}', b"",
    ))
    spawn = AsyncMock(return_value=proc)

    with patch("theswarm.tools.claude.shutil.which", return_value="/usr/bin/claude"), \
         patch("theswarm.tools.claude.asyncio.create_subprocess_exec", spawn):
        await ClaudeCLI(model="haiku")._run_cli(
            "hi", workdir=None, timeout=30, drop_oauth_env=True,
        )

    env = spawn.call_args.kwargs["env"]
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env  # long-standing rule, still enforced
