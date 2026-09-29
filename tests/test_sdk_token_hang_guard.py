"""A call that hangs before its session starts drops the env token.

#76 (2026-09-13): a stale CLAUDE_CODE_OAUTH_TOKEN made `claude -p` hang
instead of failing, and every call burned its full timeout. The token is
back in the deploy (the mounted session died during the 2026-09-28
outage), so the SDK keeps the old lesson: a timeout that never produced a
session, with the token set, is re-prompted without it — the mounted
session answers. A call that did start is resumed as before.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from theswarm.tools.claude import ClaudeCLI, ClaudeResult, _SDKTimeout


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SWARM_CLAUDE_BACKEND", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)


def _hangs_then_answers(session_id: str):
    calls: list[dict] = []

    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False,
                      resume=None, output_schema=None):
        calls.append({"drop_oauth_env": drop_oauth_env, "resume": resume})
        if len(calls) == 1:
            raise _SDKTimeout("SDK timed out after 180s", session_id=session_id)
        return ClaudeResult(text="answered")

    return run_sdk, calls


async def test_a_hang_before_the_session_with_the_token_retries_without_it(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    cli = ClaudeCLI(model="haiku")
    run_sdk, calls = _hangs_then_answers(session_id="")

    with patch.object(cli, "_run_sdk", side_effect=run_sdk):
        assert (await cli.run("hi")).text == "answered"

    assert calls[1] == {"drop_oauth_env": True, "resume": None}


async def test_a_call_that_started_is_resumed_with_its_credential(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fine")
    cli = ClaudeCLI(model="haiku")
    run_sdk, calls = _hangs_then_answers(session_id="abc-123")

    with patch.object(cli, "_run_sdk", side_effect=run_sdk):
        await cli.run("hi")

    assert calls[1] == {"drop_oauth_env": False, "resume": "abc-123"}


async def test_without_the_token_a_hang_is_re_prompted_as_before():
    cli = ClaudeCLI(model="haiku")
    run_sdk, calls = _hangs_then_answers(session_id="")

    with patch.object(cli, "_run_sdk", side_effect=run_sdk):
        await cli.run("hi")

    assert calls[1] == {"drop_oauth_env": False, "resume": None}
