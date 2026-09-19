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
    _is_timeout,
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

    async def flaky(prompt, *, workdir, timeout, drop_oauth_env=False, permission_mode=None):
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
    """Only auth failures and hangs warrant discarding the credential.

    A timeout *is* a drop trigger now (a stale token hangs rather than
    erroring), so this exercises a failure that is neither.
    """
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fine")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    calls: list[bool] = []

    async def always_transient(prompt, *, workdir, timeout, drop_oauth_env=False, permission_mode=None):
        calls.append(drop_oauth_env)
        raise _CLIUnavailable("connection reset by peer")

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

    async def failing(prompt, *, workdir, timeout, drop_oauth_env=False, permission_mode=None):
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


# ── The recovery must guard the retry too ──────────────────────────────


async def test_auth_failure_on_the_grown_retry_still_recovers(monkeypatch):
    """Prod cycle c3ab6da6f5d9: the first attempt timed out, earned its grown
    retry, and that retry died on an expired token. The recovery guarded only
    the first attempt, so the cycle had no second chance."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    attempts: list[tuple[int | None, bool]] = []

    async def flaky(prompt, *, workdir, timeout, drop_oauth_env=False, permission_mode=None):
        attempts.append((timeout, drop_oauth_env))
        if drop_oauth_env:
            return ClaudeResult(text="recovered", backend="cli")
        raise _CLIUnavailable(
            "exit 1: Failed to authenticate. API Error: 401 "
            "OAuth access token has expired.",
        )

    cli = ClaudeCLI(model="haiku", timeout=240)
    with patch.object(cli, "_run_cli", side_effect=flaky):
        result = await cli.run("hi", timeout=240)

    assert result.text == "recovered"
    # The override is dropped on the first failure, at the same budget —
    # growing the clock is for slowness, not for a credential that is wrong.
    assert attempts == [(240, False), (240, True)]


# ── A stale override can hang instead of erroring ──────────────────────


async def test_a_hang_with_the_override_set_drops_it_and_retries(monkeypatch):
    """In prod the stale token made `claude -p` hang, not fail: rc=124 after
    90s with it set, rc=0 instantly without. Recovery keyed only on auth
    errors never fired, so every call burned its timeout and the cycle died
    slowly with a message about credentials that were never the problem."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    attempts: list[bool] = []

    async def hangs_with_the_token(prompt, *, workdir, timeout, drop_oauth_env=False, permission_mode=None):
        attempts.append(drop_oauth_env)
        if not drop_oauth_env:
            raise _CLIUnavailable("CLI timed out after 240s")
        return ClaudeResult(text="recovered", backend="cli")

    cli = ClaudeCLI(model="haiku", timeout=240)
    with patch.object(cli, "_run_cli", side_effect=hangs_with_the_token):
        result = await cli.run("hi")

    assert result.text == "recovered"
    assert attempts == [False, True]


async def test_a_hang_without_the_override_is_still_just_a_timeout(monkeypatch):
    """Without the override there is nothing to drop: keep the normal retry."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    attempts: list[bool] = []

    async def always_hangs(prompt, *, workdir, timeout, drop_oauth_env=False, permission_mode=None):
        attempts.append(drop_oauth_env)
        raise _CLIUnavailable("CLI timed out after 240s")

    cli = ClaudeCLI(model="haiku", timeout=240)
    with patch.object(cli, "_run_cli", side_effect=always_hangs):
        with pytest.raises(RuntimeError):
            await cli.run("hi")

    assert True not in attempts


def test_the_deploy_no_longer_ships_the_override():
    """The token is removed at the source: prod runs on the mounted,
    self-refreshing ~/.claude session, which tested rc=0 while the override
    hung. Keeping both means the broken one wins."""
    from pathlib import Path

    for f in (".github/actions/write-env/action.yml", ".github/workflows/cd.yml"):
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in Path(f).read_text()
        assert "claude_code_oauth_token" not in Path(f).read_text()


async def test_failed_token_drop_reraises_the_original_timeout(monkeypatch):
    """The drop is a probe, not a diagnosis — it must not mask a timeout.

    Local cycle 20260919T125902Z: a 240s TechLead breakdown call timed out,
    the token-drop probe answered "OAuth session expired" in two seconds, and
    `run()` fed *that* to `_retry_timeout` — which only grows on a timeout.
    The retry got 240s again and the phase blew its 600s budget: the exact
    failure `_retry_timeout` exists to prevent (its own docstring cites prod
    cycle 11e5fe09535f dying that way).
    """
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-valid")

    async def attempts(prompt, *, workdir, timeout,
                       drop_oauth_env=False, permission_mode=None):
        if drop_oauth_env:
            raise _CLIUnavailable(
                "exit 1: Failed to authenticate: OAuth session expired"
            )
        raise _CLIUnavailable("CLI timed out after 240s")

    cli = ClaudeCLI(model="sonnet")
    with patch.object(cli, "_run_cli", side_effect=attempts):
        with pytest.raises(_CLIUnavailable) as caught:
            await cli._cli_with_auth_recovery("hi", workdir=None, timeout=240)

    assert _is_timeout(caught.value), (
        "the probe's auth error replaced the timeout, so the retry cannot "
        f"grow its budget; got: {caught.value}"
    )
