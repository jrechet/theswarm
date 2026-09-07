"""A retried timeout must get more room than the attempt that ran out.

Prod cycle 11e5fe09535f: the TechLead breakdown hit its 120s budget, was
retried with the same 120s, hit it again, and the cycle failed with
"Claude CLI failed twice". The second attempt did identical work under an
identical clock — it never had a chance.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from theswarm.tools.claude import ClaudeCLI, ClaudeResult, _CLIUnavailable, _is_timeout


@pytest.fixture(autouse=True)
def _cli_only_no_api(monkeypatch):
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)


@pytest.mark.parametrize("message, expected", [
    ("CLI timed out after 120s", True),
    ("cli TIMED OUT AFTER 240s", True),
    ("exit 1: OAuth access token has expired.", False),
    ("JSON parse failed", False),
])
def test_timeout_detection(message, expected):
    assert _is_timeout(_CLIUnavailable(message)) is expected


async def test_a_timeout_retry_gets_more_room():
    cli = ClaudeCLI(model="haiku", timeout=120, timeout_growth=1.3)
    seen: list[int | None] = []

    async def timing_out(prompt, *, workdir, timeout, drop_oauth_env=False):
        seen.append(timeout)
        if len(seen) == 1:
            raise _CLIUnavailable("CLI timed out after 120s")
        return ClaudeResult(text="recovered", backend="cli")

    with patch.object(cli, "_run_cli", side_effect=timing_out):
        result = await cli.run("hi")

    assert result.text == "recovered"
    assert seen == [None, 156]  # 120 × 1.3 — the retry can actually finish


async def test_an_explicit_call_budget_grows_from_that_budget():
    """Agents pass their own timeout; the retry must grow *that* number."""
    cli = ClaudeCLI(model="haiku", timeout=180, timeout_growth=1.3)
    seen: list[int | None] = []

    async def timing_out(prompt, *, workdir, timeout, drop_oauth_env=False):
        seen.append(timeout)
        if len(seen) == 1:
            raise _CLIUnavailable("CLI timed out after 240s")
        return ClaudeResult(text="ok", backend="cli")

    with patch.object(cli, "_run_cli", side_effect=timing_out):
        await cli.run("hi", timeout=240)

    assert seen == [240, 312]


async def test_a_non_timeout_failure_keeps_its_budget():
    """Growing the clock only helps a timeout; a crash retries as before."""
    cli = ClaudeCLI(model="haiku", timeout=120)
    seen: list[int | None] = []

    async def crashing(prompt, *, workdir, timeout, drop_oauth_env=False):
        seen.append(timeout)
        raise _CLIUnavailable("JSON parse failed")

    with patch.object(cli, "_run_cli", side_effect=crashing):
        with pytest.raises(RuntimeError):
            await cli.run("hi", timeout=90)

    assert seen == [90, 90]


async def test_both_attempts_timing_out_still_reports_the_real_cause():
    cli = ClaudeCLI(model="haiku", timeout=120)

    async def always_timeout(prompt, *, workdir, timeout, drop_oauth_env=False):
        raise _CLIUnavailable(f"CLI timed out after {timeout or 120}s")

    with patch.object(cli, "_run_cli", side_effect=always_timeout):
        with pytest.raises(RuntimeError, match="timed out after 156s"):
            await cli.run("hi")
