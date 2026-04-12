"""Shared fixtures for TheSwarm test suite."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
