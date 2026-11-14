"""A Claude call that says nothing is interrupted and resumed (A1).

The watchdog only wrote stalls in the logs, and a call that hung waited its
whole budget — 180 to 780 s — before anything happened. Every message the SDK
streams (the init, `thinking_tokens`, each tool call and result, the rate-limit
event) is a sign of life; a stream silent past its bound is cancelled — which
ends the subprocess, as the timeout did — and resumed like a timeout, on the
same budget.

And the resume itself: prod's two failed resumes (8ed99b88f26a on 2026-11-11,
one on 2026-10-18) answered the old prompt's "Finish the task and stop." with
"Understood — I'll stop and wait" and no structured answer.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from claude_agent_sdk import ResultMessage, SystemMessage

from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import SDK_CONTINUE_PROMPT, ClaudeCLI, _SDKStalled, _Silent, _within


def _init(session_id: str = "s-1") -> SystemMessage:
    return SystemMessage(subtype="init", data={"apiKeySource": "none", "session_id": session_id})


def _result() -> ResultMessage:
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                         num_turns=1, session_id="s-1", total_cost_usd=0.01,
                         usage={"input_tokens": 1, "output_tokens": 1}, result="done")


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return ClaudeCLI(model="haiku", timeout=30)


# ── The bound itself ─────────────────────────────────────────────────


async def test_a_stream_that_never_says_a_first_word_is_silent():
    loop = asyncio.get_running_loop()
    heard = {"at": loop.time(), "any": False}
    with pytest.raises(_Silent):
        await _within(asyncio.sleep(5), timeout=5, heard=heard, first_word=0.05, stall=5)


async def test_a_stream_that_keeps_talking_is_left_to_its_deadline():
    loop = asyncio.get_running_loop()
    heard = {"at": loop.time(), "any": False}

    async def talks():
        for _ in range(40):
            await asyncio.sleep(0.01)
            heard["at"], heard["any"] = loop.time(), True
        return "finished"

    assert await _within(talks(), timeout=5, heard=heard, first_word=0.05, stall=0.05) == "finished"

    heard = {"at": loop.time(), "any": False}
    with pytest.raises(asyncio.TimeoutError):
        await _within(talks(), timeout=0.1, heard=heard, first_word=0.05, stall=0.05)


async def test_a_silent_call_is_stopped_and_names_its_session(sdk, monkeypatch):
    closed = {"value": False}

    async def hangs(prompt, options):
        try:
            yield _init("s-frozen")
            await asyncio.sleep(30)
            yield _result()
        finally:
            closed["value"] = True

    monkeypatch.setattr(claude_mod, "_sdk_query", hangs)
    monkeypatch.setenv("SWARM_CLAUDE_STALL_SECONDS", "0.05")

    with pytest.raises(_SDKStalled) as info:
        await sdk._run_sdk("go", workdir="/ws", timeout=5, permission_mode=None)

    assert info.value.session_id == "s-frozen"
    assert "no word from Claude" in str(info.value)
    assert "timed out after" not in str(info.value)  # a stall never grows the budget
    assert closed["value"] is True  # the generator closed: the subprocess ends


async def test_a_call_that_never_starts_is_stopped_without_a_session(sdk, monkeypatch):
    async def never(prompt, options):
        await asyncio.sleep(30)
        yield _result()

    monkeypatch.setattr(claude_mod, "_sdk_query", never)
    monkeypatch.setenv("SWARM_CLAUDE_FIRST_WORD_SECONDS", "0.05")

    with pytest.raises(_SDKStalled) as info:
        await sdk._run_sdk("go", workdir="/ws", timeout=5, permission_mode=None)
    assert info.value.session_id == "" and "not even its first" in str(info.value)


def test_the_bounds_come_from_the_environment_or_default(monkeypatch):
    monkeypatch.delenv("SWARM_CLAUDE_FIRST_WORD_SECONDS", raising=False)
    monkeypatch.setenv("SWARM_CLAUDE_STALL_SECONDS", "nonsense")
    assert claude_mod.stall_bounds() == (claude_mod.FIRST_WORD_SECONDS, claude_mod.STALL_SECONDS)
    monkeypatch.setenv("SWARM_CLAUDE_STALL_SECONDS", "300")
    assert claude_mod.stall_bounds()[1] == 300.0


# ── The recovery: resumed on the same budget, and said ─────────────


async def test_a_stalled_call_is_resumed_on_the_same_budget_and_says_so(sdk):
    attempts: list[dict] = []
    heard: list[str] = []

    async def tell(text):
        heard.append(text)

    sdk.on_event = tell

    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False, resume=None, output_schema=None):
        attempts.append({"prompt": prompt, "timeout": timeout, "resume": resume})
        if len(attempts) == 1:
            raise _SDKStalled("SDK stalled — no word from Claude for 610s", session_id="s-1", silent_for=610)
        return claude_mod.ClaudeResult(text="finished", backend="sdk", session_id="s-1")

    with patch.object(sdk, "_run_sdk", side_effect=run_sdk):
        result = await sdk.run("implement", workdir="/ws", permission_mode="acceptEdits")

    assert result.text == "finished"
    assert attempts[1]["resume"] == "s-1" and attempts[1]["prompt"] == SDK_CONTINUE_PROMPT
    assert attempts[1]["timeout"] == sdk.timeout  # not grown: the budget was not the problem
    assert sdk._timeout_floor == 0
    assert heard == ["No word from Claude for 10 min — the call is interrupted and its session resumed"]


def test_the_resume_asks_for_the_answer_and_never_to_stop():
    prompt = SDK_CONTINUE_PROMPT.lower()
    assert "final answer" in prompt and "do not start over" in prompt
    assert "and stop" not in prompt  # "Understood — I'll stop and wait" (prod, 2026-11-11)
    assert "foreground" in prompt  # the Dev waited for a background run's notification
