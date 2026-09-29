"""What counts as an auth failure, and where the credential comes from.

The SDK's recovery (`_sdk_with_recovery`) retries once without
`CLAUDE_CODE_OAUTH_TOKEN` on an auth failure: an expired token outranks the
mounted, self-refreshing `~/.claude` session and breaks every call while
the session is valid. These tests outlived the CLI backend (V2 M7) because
the classifier and the deploy's credential rule are the SDK's too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from theswarm.tools.claude import _CLIUnavailable, _is_auth_failure


@pytest.mark.parametrize("message", [
    "exit 1: OAuth access token has expired.",
    "exit 1: Failed to authenticate. API Error: 401",
    "exit 1: Not logged in · Please run /login",
    "SDK result error: invalid API key",
])
def test_auth_failures_are_recognised(message):
    assert _is_auth_failure(_CLIUnavailable(message)) is True


@pytest.mark.parametrize("message", [
    "exit 1: connection reset by peer",
    "SDK timed out after 180s",
    "JSON parse failed",
])
def test_transient_failures_are_not_auth_failures(message):
    assert _is_auth_failure(_CLIUnavailable(message)) is False


def test_the_deploy_ships_the_token_only_when_it_is_set():
    """#76 (2026-09-13) stopped shipping a token that had gone stale; the
    mounted session then died on its own during the 2026-09-28 outage. A
    `claude setup-token` token (a year, no refresh chain) is the primary
    credential again, the mounted session the fallback (the SDK retries
    without the token on an auth failure). Optional: no secret, no line."""
    write_env = Path(".github/actions/write-env/action.yml").read_text()
    assert "claude_code_oauth_token:" in write_env
    assert 'if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then' in write_env
    assert 'echo "CLAUDE_CODE_OAUTH_TOKEN=$CLAUDE_CODE_OAUTH_TOKEN"' in write_env
    cd = Path(".github/workflows/cd.yml").read_text()
    assert cd.count("claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}") == 2  # deploy, redeploy
