"""An exhausted subscription window is a wall, not a hiccup.

Prod cycle 980dc1e098bc: the CLI returned
"You've hit your session limit · resets 9:50am (UTC)". Nothing classified
that as fatal, so the Dev loop burned its last two iterations and the whole
QA phase against it in 30 seconds and reported "CLI failed twice and no
usable API credential is available" — which says nothing about quota.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from theswarm.tools.claude import (
    ClaudeCLI,
    ClaudeFatalError,
    _CLIUnavailable,
    _quota_exhausted,
)


@pytest.fixture(autouse=True)
def _no_api_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)


@pytest.mark.parametrize("message", [
    "exit 1: You've hit your session limit · resets 9:50am (UTC)",
    "exit 1: usage limit reached",
    "CLI reported error: quota exceeded",
])
def test_quota_messages_are_recognised(message):
    assert _quota_exhausted(_CLIUnavailable(message)) == message


@pytest.mark.parametrize("message", [
    "CLI timed out after 120s",
    "exit 1: OAuth access token has expired.",
    "JSON parse failed",
])
def test_other_failures_are_not_quota(message):
    assert _quota_exhausted(_CLIUnavailable(message)) is None


async def test_quota_aborts_immediately_without_retrying():
    cli = ClaudeCLI(model="haiku")
    attempts = 0

    async def out_of_quota(prompt, *, workdir, timeout, drop_oauth_env=False):
        nonlocal attempts
        attempts += 1
        raise _CLIUnavailable(
            "exit 1: You've hit your session limit · resets 9:50am (UTC)",
        )

    with patch.object(cli, "_run_cli", side_effect=out_of_quota):
        with pytest.raises(ClaudeFatalError):
            await cli.run("hi")

    assert attempts == 1  # a wall with a clock on it: retrying cannot help


async def test_the_reset_time_survives_into_the_message():
    """The failure must tell the operator when work can resume."""
    cli = ClaudeCLI(model="haiku")

    async def out_of_quota(prompt, *, workdir, timeout, drop_oauth_env=False):
        raise _CLIUnavailable(
            "exit 1: You've hit your session limit · resets 9:50am (UTC)",
        )

    with patch.object(cli, "_run_cli", side_effect=out_of_quota):
        with pytest.raises(ClaudeFatalError, match="resets 9:50am"):
            await cli.run("hi")


async def test_a_timeout_still_gets_its_retry():
    """Only quota short-circuits; ordinary failures keep the retry path."""
    cli = ClaudeCLI(model="haiku", timeout=120)
    attempts = 0

    async def timing_out(prompt, *, workdir, timeout, drop_oauth_env=False):
        nonlocal attempts
        attempts += 1
        raise _CLIUnavailable("CLI timed out after 120s")

    with patch.object(cli, "_run_cli", side_effect=timing_out):
        with pytest.raises(RuntimeError):
            await cli.run("hi")

    assert attempts == 2
