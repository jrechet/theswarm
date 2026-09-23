"""`python -m theswarm validate` reports the Agent SDK probe (V2 runtime, M0).

The probe spawns a real Claude Code binary, so it must never run under the
suite's default backend (`api`, set in tests/conftest.py): a forced API
backend makes the SDK irrelevant, and that is the rule the command applies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from theswarm.presentation.cli.main import main


def _report(**overrides) -> dict:
    report = {
        "ok": True, "identity": "subscription", "model": "claude-haiku-4-5",
        "session_id": "s-1", "cost_usd": 0.01, "claude_code_version": "2.1.280",
        "binary": "bundled:/x/claude", "error": "",
    }
    report.update(overrides)
    return report


def _configured(monkeypatch, backend: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "mm-test")
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", backend)


def test_validate_reports_the_sdk_probe(monkeypatch, capsys):
    _configured(monkeypatch, "auto")
    with patch("theswarm.tools.claude.probe_sdk", AsyncMock(return_value=_report())) as probe:
        main(["validate"])
    assert probe.await_count == 1
    out = capsys.readouterr().out
    assert "Agent SDK: ok" in out
    assert "subscription" in out
    assert "2.1.280" in out
    assert "Validation passed" in out


def test_validate_skips_the_probe_when_the_backend_is_forced_to_api(monkeypatch, capsys):
    _configured(monkeypatch, "api")
    with patch("theswarm.tools.claude.probe_sdk", AsyncMock(return_value=_report())) as probe:
        main(["validate"])
    assert probe.await_count == 0
    assert "Agent SDK: skipped" in capsys.readouterr().out


def test_validate_warns_but_passes_when_the_probe_fails(monkeypatch, capsys):
    _configured(monkeypatch, "auto")
    failed = _report(ok=False, identity="unknown", error="OAuth session expired")
    with patch("theswarm.tools.claude.probe_sdk", AsyncMock(return_value=failed)):
        main(["validate"])
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "OAuth session expired" in out
    assert "Validation passed" in out
