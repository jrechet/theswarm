"""V2 runtime, M1: the Agent SDK backend behind ``ClaudeCLI``.

Same contract as the CLI path (``run`` → ``ClaudeResult``), a different
transport: a stream of typed messages instead of one JSON envelope. What
the tests pin down is what the plan's invariants demand
(docs/plans/2026-09-v2-runtime.md, §3 and §5 M1):

- I1/I2: the child env never carries ANTHROPIC_API_KEY; no host settings.
- Permissions live in code: an allowlist per call profile and a callback
  that refuses pushes, `gh`, secrets and anything outside the workspace.
- A timeout is resumed, not re-prompted; an auth failure retries once
  without the OAuth override; an exhausted window is fatal (I6).
- The theater gets one event per tool call and one per text block, never
  file contents, never a token.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import (
    SDK_CONTINUE_PROMPT,
    ClaudeCLI,
    ClaudeFatalError,
    _CLIUnavailable,
    _SDKTimeout,
    decide_tool_use,
)


def _init(session_id: str = "s-1") -> SystemMessage:
    return SystemMessage(subtype="init", data={
        "apiKeySource": "none", "claude_code_version": "2.1.280",
        "model": "claude-haiku-4-5", "session_id": session_id,
    })


def _assistant(*blocks) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="claude-haiku-4-5")


def _result(**overrides) -> ResultMessage:
    fields = dict(
        subtype="success", duration_ms=10, duration_api_ms=8, is_error=False,
        num_turns=3, session_id="s-1", total_cost_usd=0.25,
        usage={"input_tokens": 100, "output_tokens": 40,
               "cache_creation_input_tokens": 9000, "cache_read_input_tokens": 0},
        result="done — edited two files",
    )
    fields.update(overrides)
    return ResultMessage(**fields)


def _queries(*message_lists):
    """A fake ``_sdk_query``: each call yields the next list of messages and
    records the (prompt, options) it was given."""
    calls: list[dict] = []
    remaining = list(message_lists)

    async def fake(prompt, options):
        calls.append({"prompt": prompt, "options": options})
        messages = remaining.pop(0) if remaining else [_result()]
        for message in messages:
            if isinstance(message, BaseException):
                raise message
            yield message

    return fake, calls


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return ClaudeCLI(model="haiku", timeout=30)


# ── The contract: ClaudeResult, same as the CLI path ─────────────────


async def test_sdk_backend_maps_the_result(sdk, monkeypatch):
    fake, calls = _queries([_init(), _assistant(TextBlock("working")), _result()])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    result = await sdk.run("do the thing", workdir="/ws", permission_mode="acceptEdits")

    assert result.text == "done — edited two files"
    assert result.backend == "sdk"
    assert result.input_tokens == 100
    assert result.output_tokens == 40
    assert result.total_tokens == 140
    assert result.cost_usd == pytest.approx(0.25)
    assert result.model == "claude-haiku-4-5"
    assert result.session_id == "s-1"
    assert result.num_turns == 3
    assert calls[0]["prompt"] == "do the thing"


async def test_backend_mode_accepts_sdk(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    assert claude_mod._resolve_backend_mode() == "sdk"


# ── Options per call profile ─────────────────────────────────────────


async def test_an_edit_call_gets_the_edit_profile(sdk, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    fake, calls = _queries([_init(), _result()])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    await sdk.run("implement", workdir="/ws", permission_mode="acceptEdits")

    options = calls[0]["options"]
    assert isinstance(options, ClaudeAgentOptions)
    assert options.cwd == "/ws"
    assert options.permission_mode == "acceptEdits"
    assert options.model == "claude-haiku-4-5"
    for tool in ("Read", "Edit", "Write", "Glob", "Grep"):
        assert tool in options.allowed_tools
    # Bash is decided call by call, never auto-allowed
    assert "Bash" not in options.allowed_tools
    for tool in ("WebSearch", "WebFetch", "Task"):
        assert tool in options.disallowed_tools
    assert options.setting_sources == []          # I2: nothing from the host
    # I1: the SDK merges options.env over os.environ, so the key must be
    # overridden to empty, not omitted (see _sdk_child_env).
    assert options.env["ANTHROPIC_API_KEY"] == ""
    assert {**os.environ, **options.env}["ANTHROPIC_API_KEY"] == ""
    assert options.env["CI"] == "1"
    assert options.can_use_tool is not None
    # The policy sits in a PreToolUse hook: allowed_tools auto-approves file
    # tools *before* can_use_tool, and reads never ask — only a hook sees
    # every call (the SDK's own CanUseToolShadowedWarning says so).
    matchers = options.hooks["PreToolUse"]
    assert len(matchers) == 1 and matchers[0].matcher is None and len(matchers[0].hooks) == 1
    assert options.max_turns and options.max_turns >= 100
    assert options.system_prompt == {"type": "preset", "preset": "claude_code"}
    assert options.resume is None


async def test_a_read_only_call_gets_the_read_profile(sdk, monkeypatch):
    fake, calls = _queries([_init(), _result()])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    await sdk.run("write e2e tests", workdir="/ws")

    options = calls[0]["options"]
    assert options.cwd == "/ws"
    assert options.permission_mode == "default"
    assert set(options.allowed_tools) == {"Read", "Glob", "Grep"}
    assert options.can_use_tool is not None
    assert options.system_prompt == {"type": "preset", "preset": "claude_code"}


async def test_a_call_without_a_workdir_gets_the_text_profile(sdk, monkeypatch):
    fake, calls = _queries([_init(), _result()])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    await sdk.run("review this diff")

    options = calls[0]["options"]
    assert options.cwd is None
    assert options.allowed_tools == []
    assert options.permission_mode == "default"
    assert options.max_turns is not None and options.max_turns <= 10
    assert options.system_prompt is None


# ── The permission policy, as a pure function ────────────────────────


@pytest.mark.parametrize("command", [
    "git push origin feat/x",
    "git push --force",
    "gh pr create --fill",
    "gh api repos/x/y",
    "cat .env",
    "cat ./.env.local",
    "git config user.email x@y",
    "git remote set-url origin https://x",
])
def test_edit_profile_refuses_dangerous_bash(command):
    allowed, reason = decide_tool_use("edit", "/ws", "Bash", {"command": command})
    assert allowed is False
    assert reason


@pytest.mark.parametrize("command", [
    "pytest -q tests/",
    "git status",
    "git add -A && git commit -m x",
    "ls -la src",
    "python -m pytest tests/test_x.py",
])
def test_edit_profile_allows_ordinary_bash(command):
    allowed, _ = decide_tool_use("edit", "/ws", "Bash", {"command": command})
    assert allowed is True


def test_read_profile_refuses_bash_and_edits():
    assert decide_tool_use("read", "/ws", "Bash", {"command": "ls"})[0] is False
    assert decide_tool_use("read", "/ws", "Edit", {"file_path": "/ws/a.py"})[0] is False
    assert decide_tool_use("read", "/ws", "Read", {"file_path": "/ws/a.py"})[0] is True


def test_paths_must_stay_inside_the_workspace():
    assert decide_tool_use("edit", "/ws", "Edit", {"file_path": "/ws/src/a.py"})[0] is True
    assert decide_tool_use("edit", "/ws", "Edit", {"file_path": "src/a.py"})[0] is True
    assert decide_tool_use("edit", "/ws", "Edit", {"file_path": "/etc/passwd"})[0] is False
    assert decide_tool_use("edit", "/ws", "Edit", {"file_path": "/ws/../other/a.py"})[0] is False
    assert decide_tool_use("edit", "/ws", "Write", {"file_path": "/ws/.git/config"})[0] is False
    assert decide_tool_use("edit", "/ws", "Read", {"file_path": "/ws/.env"})[0] is False
    assert decide_tool_use("edit", "/ws", "Read", {"file_path": "/ws/.env.production"})[0] is False


async def test_the_pre_tool_use_hook_denies_with_a_reason_and_passes_otherwise():
    from theswarm.tools.claude import _permission_hook

    hook = _permission_hook("edit", "/ws")
    denied = await hook({"tool_name": "Read", "tool_input": {"file_path": "/etc/hostname"}}, "t1", None)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "outside the workspace" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    assert denied["hookSpecificOutput"]["hookEventName"] == "PreToolUse"

    passed = await hook({"tool_name": "Edit", "tool_input": {"file_path": "/ws/a.py"}}, "t2", None)
    assert passed == {}

    no_tools = _permission_hook("text", None)
    denied = await no_tools({"tool_name": "Read", "tool_input": {"file_path": "x"}}, "t3", None)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_unknown_tools_are_refused_everywhere():
    for profile in ("edit", "read", "text"):
        assert decide_tool_use(profile, "/ws", "WebSearch", {"query": "x"})[0] is False
        assert decide_tool_use(profile, "/ws", "Task", {})[0] is False


# ── What the theater sees ────────────────────────────────────────────


async def test_tool_calls_and_text_blocks_reach_the_callback_once_each(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret123")
    events: list[str] = []

    async def on_event(message: str) -> None:
        events.append(message)

    fake, _ = _queries([
        _init(),
        _assistant(
            TextBlock("Let me read the model first.\nSecond line is not shown."),
            ToolUseBlock(id="t1", name="Read", input={"file_path": "/ws/src/models.py"}),
        ),
        _assistant(ToolUseBlock(id="t2", name="Write", input={
            "file_path": "/ws/src/new.py", "content": "SECRET_CONTENT = 1\n",
        })),
        _assistant(ToolUseBlock(id="t3", name="Bash", input={
            "command": "git ls-remote https://x:ghp_secret123@github.com/a/b && pytest -q",
        })),
        _result(),
    ])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    await ClaudeCLI(model="haiku", on_event=on_event).run(
        "go", workdir="/ws", permission_mode="acceptEdits",
    )

    assert len(events) == 4
    assert events[0] == "Let me read the model first."
    assert events[1] == "Read src/models.py"
    assert events[2] == "Write src/new.py"
    assert "SECRET_CONTENT" not in " ".join(events)
    assert events[3].startswith("Bash: ")
    assert "ghp_secret123" not in events[3]
    assert "pytest -q" in events[3]


async def test_a_failing_callback_never_fails_the_call(sdk, monkeypatch):
    fake, _ = _queries([_init(), _assistant(TextBlock("hi")), _result()])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)
    sdk.on_event = AsyncMock(side_effect=RuntimeError("bridge down"))

    result = await sdk.run("go", workdir="/ws")

    assert result.text == "done — edited two files"


# ── Failure handling: resume, auth, quota, forced mode ───────────────


async def test_a_timeout_closes_the_stream_and_names_the_session(sdk, monkeypatch):
    closed = {"value": False}

    async def slow(prompt, options):
        try:
            yield _init("s-slow")
            await asyncio.sleep(30)
            yield _result()
        finally:
            closed["value"] = True

    monkeypatch.setattr(claude_mod, "_sdk_query", slow)

    with pytest.raises(_SDKTimeout) as info:
        await sdk._run_sdk("go", workdir="/ws", timeout=0.05, permission_mode=None)

    assert info.value.session_id == "s-slow"
    assert "timed out after" in str(info.value)
    assert closed["value"] is True


async def test_a_timeout_is_resumed_with_more_room(sdk):
    attempts: list[dict] = []

    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False, resume=None, output_schema=None):
        attempts.append({"prompt": prompt, "timeout": timeout, "resume": resume})
        if len(attempts) == 1:
            raise _SDKTimeout("SDK timed out after 30s", session_id="s-1")
        return claude_mod.ClaudeResult(text="finished", backend="sdk", session_id="s-1")

    with patch.object(sdk, "_run_sdk", side_effect=run_sdk):
        result = await sdk.run("implement", workdir="/ws", permission_mode="acceptEdits")

    assert result.text == "finished"
    assert len(attempts) == 2
    assert attempts[1]["resume"] == "s-1"
    assert attempts[1]["prompt"] == SDK_CONTINUE_PROMPT
    assert attempts[0]["timeout"] is None  # the caller's None, resolved by _effective_timeout
    assert attempts[1]["timeout"] > sdk.timeout


async def test_a_second_timeout_surfaces_as_a_failed_call(sdk):
    async def always(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False, resume=None, output_schema=None):
        raise _SDKTimeout("SDK timed out after 30s", session_id="s-1")

    with patch.object(sdk, "_run_sdk", side_effect=always):
        with pytest.raises(RuntimeError, match="Claude SDK"):
            await sdk.run("implement", workdir="/ws", permission_mode="acceptEdits")


async def test_an_auth_failure_retries_once_without_the_oauth_override(sdk, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    attempts: list[bool] = []

    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False, resume=None, output_schema=None):
        attempts.append(drop_oauth_env)
        if not drop_oauth_env:
            raise _CLIUnavailable("Failed to authenticate: OAuth session expired")
        return claude_mod.ClaudeResult(text="recovered", backend="sdk")

    with patch.object(sdk, "_run_sdk", side_effect=run_sdk):
        result = await sdk.run("hi")

    assert result.text == "recovered"
    assert attempts == [False, True]


async def test_an_auth_failure_without_an_override_is_just_a_failure(sdk):
    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False, resume=None, output_schema=None):
        raise _CLIUnavailable("Failed to authenticate: OAuth session expired")

    with patch.object(sdk, "_run_sdk", side_effect=run_sdk) as spy:
        with pytest.raises(RuntimeError, match="Claude SDK"):
            await sdk.run("hi")
    assert spy.await_count == 1


async def test_an_exhausted_window_is_fatal(sdk):
    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False, resume=None, output_schema=None):
        raise _CLIUnavailable("You've hit your usage limit — resets at 3pm")

    with patch.object(sdk, "_run_sdk", side_effect=run_sdk):
        with pytest.raises(ClaudeFatalError, match="usage limit"):
            await sdk.run("hi")


async def test_forced_sdk_never_falls_back_to_the_api(sdk, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")

    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False, resume=None, output_schema=None):
        raise _CLIUnavailable("CLINotFoundError: no binary")

    with patch.object(sdk, "_run_sdk", side_effect=run_sdk), \
         patch.object(sdk, "_run_api", new=AsyncMock()) as api:
        with pytest.raises(RuntimeError, match="Claude SDK"):
            await sdk.run("hi")
    assert api.await_count == 0


async def test_a_call_answered_by_an_api_key_is_refused(sdk, monkeypatch):
    """I1 on every call: the init message names the identity before any
    work happens; an API key there stops the call, whatever follows."""
    keyed = SystemMessage(subtype="init", data={
        "apiKeySource": "ANTHROPIC_API_KEY", "session_id": "s-1",
    })
    fake, _ = _queries([keyed, _assistant(TextBlock("hi")), _result()])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await sdk.run("hi")


async def test_an_error_result_is_a_failed_call(sdk, monkeypatch):
    fake, _ = _queries([_init(), _result(
        subtype="error_during_execution", is_error=True, result="something broke",
    )])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    with pytest.raises(RuntimeError, match="something broke"):
        await sdk.run("hi")


async def test_the_sdk_raising_mid_stream_is_a_failed_call(sdk, monkeypatch):
    fake, _ = _queries([_init(), RuntimeError("ProcessError: exit 1")])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    with pytest.raises(RuntimeError, match="ProcessError"):
        await sdk.run("hi")


def test_the_structured_answer_is_never_refused():
    """With output_format the answer arrives as a StructuredOutput call.

    Cycle 71c8b870041a: the text profile allows no tool, the hook refused
    the pseudo-tool three times and the breakdown failed with "no
    structured output for the requested schema".
    """
    from theswarm.tools.claude import decide_tool_use

    for profile in ("text", "read", "edit"):
        allowed, why = decide_tool_use(profile, "/ws", "StructuredOutput", {"tasks": []})
        assert allowed, (profile, why)
    assert decide_tool_use("text", None, "Bash", {"command": "ls"})[0] is False


def test_the_structured_output_pseudo_tool_is_silent():
    from theswarm.tools.claude import _tool_event

    assert _tool_event("StructuredOutput", {"tasks": [{"title": "x"}]}, "/ws") == ""
    assert _tool_event("Read", {"file_path": "/ws/a.py"}, "/ws") == "Read a.py"


def test_no_child_reads_the_hosts_auto_memory():
    """Cycle 71c8b870041a: the PO tried to Read memory files an earlier run
    left in the container's ~/.claude — host state reaching an agent (I2)."""
    from theswarm.tools.claude import _child_env, _sdk_child_env

    assert _child_env()["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert _sdk_child_env()["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


@pytest.mark.parametrize("text,expected", [
    ("Let me read the model first.\nSecond line.", "Let me read the model first."),
    ("import uuid\nimport pytest\n\ndef test_x():\n    pass\n", ""),
    ("```json\n{\"decision\": \"APPROVE\"}\n```", ""),
    ("# heading\nThe fix is in.", "The fix is in."),
    ("   \n\n", ""),
])
def test_text_events_skip_code_and_keep_prose(text, expected):
    from theswarm.tools.claude import _text_event

    assert _text_event(text) == expected


def test_each_profile_sees_only_the_tools_its_policy_allows():
    """A tool the model can see but not use is a turn spent asking for it:
    the breakdown of cycle a6d93287668b asked for Bash twice and for
    AskUserQuestion once before answering."""
    from theswarm.tools.claude import ClaudeCLI, _SDK_PROFILE_TOOLS

    cli = ClaudeCLI(model="haiku")
    for profile in ("text", "read", "edit"):
        opts = cli._sdk_options(
            profile, "/ws" if profile != "text" else None, "claude-haiku-4-5",
            drop_oauth_env=False, resume=None,
        )
        assert sorted(opts.tools) == sorted(_SDK_PROFILE_TOOLS[profile]), profile
    text = cli._sdk_options("text", None, "claude-haiku-4-5", drop_oauth_env=False, resume=None)
    assert text.tools == []


@pytest.mark.parametrize("raw,expected", [("", 200), ("1", 1), ("0", 200), ("x", 200), ("12", 12)])
def test_the_edit_turn_ceiling_can_be_lowered_for_a_deliberate_regression(monkeypatch, raw, expected):
    """V2 runtime M6 acceptance: a day with SWARM_SDK_MAX_TURNS_EDIT=1 must
    read as failed eval runs, then recover when the variable is removed."""
    from theswarm.tools.claude import ClaudeCLI

    monkeypatch.setenv("SWARM_SDK_MAX_TURNS_EDIT", raw)
    opts = ClaudeCLI(model="haiku")._sdk_options(
        "edit", "/ws", "claude-haiku-4-5", drop_oauth_env=False, resume=None,
    )
    assert opts.max_turns == expected
