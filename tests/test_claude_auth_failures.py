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


def test_the_deploy_no_longer_ships_the_override():
    """Prod runs on the mounted, self-refreshing ~/.claude session (I1);
    shipping the token as well means the broken one wins."""
    for f in (".github/actions/write-env/action.yml", ".github/workflows/cd.yml"):
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in Path(f).read_text()
        assert "claude_code_oauth_token" not in Path(f).read_text()
