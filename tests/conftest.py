"""Shared fixtures for TheSwarm test suite."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _default_claude_backend_for_tests(monkeypatch):
    """Force API backend in tests unless the test explicitly opts into CLI.

    Production defaults to CLI-first so the Claude Code subscription is used
    instead of API credits. Tests mock the Anthropic SDK directly, so they
    need the API path — otherwise they would spawn the real ``claude`` CLI.
    Tests that want to exercise the CLI path can override with
    ``monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "cli")``.
    """
    if "SWARM_CLAUDE_BACKEND" not in os.environ:
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "api")


@pytest.fixture()
def mock_settings():
    """Return a SwarmSettings-like object without importing pydantic models."""
    settings = MagicMock()
    settings.server.host = "127.0.0.1"
    settings.server.port = 8091
    settings.agents.swarm_po.mm_token = ""
    settings.agents.swarm_po.github_repos = []
    settings.agents.swarm_po.default_repo = ""
    settings.mattermost.url = "https://mm.example.com"
    settings.mattermost.token = ""
    return settings


@pytest.fixture()
def gateway(mock_settings):
    """Create a SwarmGateway with mock settings."""
    from theswarm.gateway.app import SwarmGateway

    gw = SwarmGateway(mock_settings)
    return gw


@pytest.fixture()
def mock_github_client():
    """Return a mock GitHubClient with common async methods stubbed."""
    client = MagicMock()
    client.repo_name = "owner/repo"
    client.get_issues = AsyncMock(return_value=[])
    client.get_file_content = AsyncMock(return_value="")
    client.update_file = AsyncMock(return_value=None)
    client.create_pull_request = AsyncMock(return_value={"number": 1})
    return client
