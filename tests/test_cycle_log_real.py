"""Tests for cycle_log.py — append_cycle_log in real mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_config(*, real: bool = True, repo: str = "owner/repo"):
    config = MagicMock()
    config.is_real_mode = real
    config.github_repo = repo
    return config


def _make_result():
    return {
        "date": "2026-04-06",
        "tokens": 50000,
        "cost_usd": 1.23,
        "prs": [{"number": 1}, {"number": 2}],
        "reviews": [{"decision": "APPROVE"}, {"decision": "REQUEST_CHANGES"}],
        "demo_report": {"overall_status": "pass"},
    }


async def test_append_stub_mode():
    """Stub mode skips writing and returns True."""
    from theswarm.cycle_log import append_cycle_log

    config = _make_config(real=False)
    result = await append_cycle_log(config, _make_result())
    assert result is True


async def test_append_real_mode_new_file():
    """Creates entry when file doesn't exist yet."""
    from theswarm.cycle_log import append_cycle_log

    mock_github = AsyncMock()
    mock_github.get_file_content = AsyncMock(side_effect=Exception("Not found"))
    mock_github.update_file = AsyncMock()

    config = _make_config()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        result = await append_cycle_log(config, _make_result())

    assert result is True
    mock_github.update_file.assert_awaited_once()
    call_kwargs = mock_github.update_file.call_args[1]
    assert "cycle-history.jsonl" in call_kwargs["path"]
    assert "2026-04-06" in call_kwargs["content"]


async def test_append_real_mode_existing_file():
    """Appends to existing content."""
    from theswarm.cycle_log import append_cycle_log

    existing = '{"timestamp":"old","date":"2026-04-05"}\n'
    mock_github = AsyncMock()
    mock_github.get_file_content = AsyncMock(return_value=existing)
    mock_github.update_file = AsyncMock()

    config = _make_config()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        result = await append_cycle_log(config, _make_result())

    assert result is True
    content = mock_github.update_file.call_args[1]["content"]
    lines = content.strip().split("\n")
    assert len(lines) == 2  # existing + new


async def test_append_real_mode_entry_fields():
    """Verify the JSONL entry has expected fields."""
    import json
    from theswarm.cycle_log import append_cycle_log

    mock_github = AsyncMock()
    mock_github.get_file_content = AsyncMock(return_value="")
    mock_github.update_file = AsyncMock()

    config = _make_config()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        await append_cycle_log(config, _make_result())

    content = mock_github.update_file.call_args[1]["content"]
    entry = json.loads(content.strip())
    assert entry["date"] == "2026-04-06"
    assert entry["cost_usd"] == 1.23
    assert entry["prs_opened"] == 2
    assert entry["prs_merged"] == 1  # only 1 APPROVE
    assert entry["demo_status"] == "pass"
    assert entry["repo"] == "owner/repo"


async def test_append_real_mode_failure():
    """Returns False when GitHub write fails."""
    from theswarm.cycle_log import append_cycle_log

    mock_github = AsyncMock()
    mock_github.get_file_content = AsyncMock(return_value="")
    mock_github.update_file = AsyncMock(side_effect=Exception("API error"))

    config = _make_config()
    with patch("theswarm.tools.github.GitHubClient", return_value=mock_github):
        result = await append_cycle_log(config, _make_result())

    assert result is False
