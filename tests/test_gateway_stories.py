"""Tests for theswarm.gateway.stories — story generation and approval flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def gw_with_github(gateway):
    """Gateway with a mock GitHub repo and chat attached."""
    mock_repo = MagicMock()
    gateway._swarm_po_github = mock_repo
    gateway._swarm_po_chat = AsyncMock()
    gateway._swarm_po_pending_stories = {}
    return gateway


# ── generate_stories ─────────────────────────────────────────────────


async def test_generate_stories_parses_json_array(gateway):
    mock_result = MagicMock()
    mock_result.text = json.dumps([
        {"title": "US: Login", "description": "As a user..."},
        {"title": "US: Signup", "description": "As a new user..."},
    ])

    with patch("theswarm.tools.claude.ClaudeCLI") as mock_cli_cls:
        mock_cli = AsyncMock()
        mock_cli.run.return_value = mock_result
        mock_cli_cls.return_value = mock_cli

        from theswarm.gateway.stories import generate_stories
        stories = await generate_stories(gateway, "Add auth feature")

    assert len(stories) == 2
    assert stories[0]["title"] == "US: Login"


async def test_generate_stories_strips_markdown_fences(gateway):
    mock_result = MagicMock()
    mock_result.text = '```json\n[{"title": "US: Test"}]\n```'

    with patch("theswarm.tools.claude.ClaudeCLI") as mock_cli_cls:
        mock_cli = AsyncMock()
        mock_cli.run.return_value = mock_result
        mock_cli_cls.return_value = mock_cli

        from theswarm.gateway.stories import generate_stories
        stories = await generate_stories(gateway, "Test feature")

    assert len(stories) == 1


async def test_generate_stories_handles_dict_wrapper(gateway):
    mock_result = MagicMock()
    mock_result.text = json.dumps({"stories": [{"title": "US: X"}]})

    with patch("theswarm.tools.claude.ClaudeCLI") as mock_cli_cls:
        mock_cli = AsyncMock()
        mock_cli.run.return_value = mock_result
        mock_cli_cls.return_value = mock_cli

        from theswarm.gateway.stories import generate_stories
        stories = await generate_stories(gateway, "X feature")

    assert len(stories) == 1


async def test_generate_stories_returns_empty_on_error(gateway):
    with patch("theswarm.tools.claude.ClaudeCLI") as mock_cli_cls:
        mock_cli = AsyncMock()
        mock_cli.run.side_effect = Exception("API error")
        mock_cli_cls.return_value = mock_cli

        from theswarm.gateway.stories import generate_stories
        stories = await generate_stories(gateway, "Broken")

    assert stories == []


# ── store_pending_stories ────────────────────────────────────────────


async def test_store_pending_stories(gateway):
    gateway._swarm_po_pending_stories = {}
    from theswarm.gateway.stories import store_pending_stories
    pending_id = await store_pending_stories(gateway, "user1", [{"title": "US: Test"}])

    assert len(pending_id) == 8
    assert "user1" == gateway._swarm_po_pending_stories[pending_id]["user_id"]


# ── create_issues ────────────────────────────────────────────────────


async def test_create_issues_no_vcs(gateway):
    gateway._swarm_po_github = None
    gateway._swarm_po_chat = AsyncMock()

    from theswarm.gateway.stories import create_issues
    await create_issues(gateway, "user1", [{"title": "US: Test"}])

    gateway._swarm_po_chat.post_dm.assert_awaited_once()
    assert "not configured" in gateway._swarm_po_chat.post_dm.call_args[0][1]


async def test_create_issues_success(gw_with_github):
    mock_issue = MagicMock()
    mock_issue.number = 42
    gw_with_github._swarm_po_github.create_issue = MagicMock(return_value=mock_issue)

    from theswarm.gateway.stories import create_issues
    await create_issues(gw_with_github, "user1", [{"title": "US: Test", "description": "desc"}])

    msg = gw_with_github._swarm_po_chat.post_dm.call_args[0][1]
    assert "#42" in msg
    assert "1" in msg


async def test_create_issues_partial_failure(gw_with_github):
    mock_issue = MagicMock()
    mock_issue.number = 1

    call_count = 0
    def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("GitHub error")
        return mock_issue

    gw_with_github._swarm_po_github.create_issue = side_effect

    from theswarm.gateway.stories import create_issues
    await create_issues(gw_with_github, "user1", [
        {"title": "US: Fail"},
        {"title": "US: Ok"},
    ])

    msg = gw_with_github._swarm_po_chat.post_dm.call_args[0][1]
    assert "1" in msg  # 1 created
