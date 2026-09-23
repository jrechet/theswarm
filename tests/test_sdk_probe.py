"""M0 of the V2 runtime (docs/plans/2026-09-v2-runtime.md): the Agent SDK
probe, and the child environment every SDK call receives.

The SDK runs the Claude Code binary. In that binary's credential precedence
ANTHROPIC_API_KEY (rank 3) sits above CLAUDE_CODE_OAUTH_TOKEN (rank 5), so an
API key left in the child env silently moves a cycle from the subscription to
per-token billing (invariant I1). Host-level settings and hooks must not be
loaded either (I2): a Stop hook of the host once voided the swarm's reviews.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, SystemMessage

from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import _child_env, _sdk_child_env, probe_sdk


def _init(api_key_source: str | None = "none") -> SystemMessage:
    data = {
        "claude_code_version": "2.1.280",
        "model": "claude-haiku-4-5",
        "session_id": "s-1",
    }
    if api_key_source is not None:
        data["apiKeySource"] = api_key_source
    return SystemMessage(subtype="init", data=data)


def _result(**overrides) -> ResultMessage:
    fields = dict(
        subtype="success", duration_ms=10, duration_api_ms=8, is_error=False,
        num_turns=1, session_id="s-1", total_cost_usd=0.0123,
        usage={"input_tokens": 10, "output_tokens": 2}, result="OK",
    )
    fields.update(overrides)
    return ResultMessage(**fields)


def _fake_query(messages, captured: dict):
    async def fake(prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        for message in messages:
            yield message
    return fake


# ── _child_env: what a Claude Code process is allowed to see ─────────


def test_child_env_never_carries_the_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-sub")
    env = _child_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-sub"
    assert env["CI"] == "1"
    assert env["CLAUDE_CODE_NON_INTERACTIVE"] == "1"


def test_child_env_can_drop_the_oauth_override(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in _child_env(drop_oauth_env=True)


def test_child_env_does_not_mutate_the_process_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    _child_env()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-real"


# ── _sdk_child_env: what the SDK's transport actually hands the child ─


def _as_the_sdk_transport_merges(options_env: dict) -> dict:
    """claude_agent_sdk/_internal/transport/subprocess_cli.py builds the
    child env as ``{**os.environ, **options.env}``: options.env overrides,
    it does not replace. This mirrors that merge so the test sees what the
    binary sees, not what we handed the SDK."""
    return {**os.environ, **options_env}


def test_sdk_child_env_overrides_the_api_key_to_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-should-not-leak")
    child = _as_the_sdk_transport_merges(_sdk_child_env())
    assert child["ANTHROPIC_API_KEY"] == ""
    assert child["CI"] == "1"


def test_omission_alone_would_leak_through_the_merge(monkeypatch):
    """The regression this guards: the CLI-style env (key omitted) is not
    enough for the SDK. Measured 2026-09-23: apiKeySource=ANTHROPIC_API_KEY."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-should-not-leak")
    child = _as_the_sdk_transport_merges(_child_env())
    assert child["ANTHROPIC_API_KEY"] == "sk-ant-api03-should-not-leak"


def test_sdk_child_env_drops_the_oauth_override_without_shadowing_it(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-stale")
    env = _sdk_child_env(drop_oauth_env=True)
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


# ── probe_sdk: one turn, and it says who answered ────────────────────


async def test_probe_reports_the_subscription_identity(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        claude_mod, "_sdk_query", _fake_query([_init("none"), _result()], captured),
    )
    report = await probe_sdk(timeout=5)
    assert report["ok"] is True
    assert report["identity"] == "subscription"
    assert report["session_id"] == "s-1"
    assert report["cost_usd"] == pytest.approx(0.0123)
    assert report["claude_code_version"] == "2.1.280"
    assert report["error"] == ""


async def test_probe_options_scrub_the_env_and_load_no_host_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-real")
    captured: dict = {}
    monkeypatch.setattr(
        claude_mod, "_sdk_query", _fake_query([_init(), _result()], captured),
    )
    await probe_sdk(timeout=5)
    options = captured["options"]
    assert isinstance(options, ClaudeAgentOptions)
    assert options.env["ANTHROPIC_API_KEY"] == ""  # an explicit override, see _sdk_child_env
    assert _as_the_sdk_transport_merges(options.env)["ANTHROPIC_API_KEY"] == ""
    assert options.env["CI"] == "1"
    assert options.setting_sources == []
    assert options.max_turns == 1
    assert options.allowed_tools == []


async def test_probe_flags_an_api_key_identity_as_a_violation(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        claude_mod, "_sdk_query",
        _fake_query([_init("ANTHROPIC_API_KEY"), _result()], captured),
    )
    report = await probe_sdk(timeout=5)
    assert report["ok"] is False
    assert report["identity"] == "api-key"
    assert "ANTHROPIC_API_KEY" in report["error"]


async def test_probe_without_an_identity_is_not_ok(monkeypatch):
    """An init message without apiKeySource confirms nothing."""
    captured: dict = {}
    monkeypatch.setattr(
        claude_mod, "_sdk_query", _fake_query([_init(None), _result()], captured),
    )
    report = await probe_sdk(timeout=5)
    assert report["ok"] is False
    assert report["identity"] == "unknown"
    assert "did not confirm" in report["error"]


async def test_probe_reports_a_broken_sdk_without_raising(monkeypatch):
    class Broken:
        def __init__(self, **kwargs):
            raise TypeError("unexpected keyword 'setting_sources'")

    import claude_agent_sdk
    monkeypatch.setattr(claude_agent_sdk, "ClaudeAgentOptions", Broken)
    report = await probe_sdk(timeout=5)
    assert report["ok"] is False
    assert "unavailable" in report["error"]


async def test_probe_reports_an_error_result(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        claude_mod, "_sdk_query",
        _fake_query([_init(), _result(
            subtype="error_during_execution", is_error=True,
            result="OAuth session expired",
        )], captured),
    )
    report = await probe_sdk(timeout=5)
    assert report["ok"] is False
    assert "OAuth session expired" in report["error"]


async def test_probe_with_no_result_message_is_not_ok(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(claude_mod, "_sdk_query", _fake_query([_init()], captured))
    report = await probe_sdk(timeout=5)
    assert report["ok"] is False
    assert "no result" in report["error"]


async def test_probe_survives_a_raising_sdk(monkeypatch):
    async def boom(prompt, options):
        raise RuntimeError("Claude Code returned an error result: Failed to authenticate")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(claude_mod, "_sdk_query", boom)
    report = await probe_sdk(timeout=5)
    assert report["ok"] is False
    assert "Failed to authenticate" in report["error"]


async def test_probe_times_out_instead_of_hanging(monkeypatch):
    async def hangs(prompt, options):
        await asyncio.sleep(60)
        yield _result()

    monkeypatch.setattr(claude_mod, "_sdk_query", hangs)
    report = await probe_sdk(timeout=0.05)
    assert report["ok"] is False
    assert "timed out" in report["error"]


def test_binary_location_names_the_bundled_binary_or_the_path_one():
    location = claude_mod.sdk_binary_location()
    assert location.startswith(("bundled:", "path:"))
    assert location.endswith("claude")
