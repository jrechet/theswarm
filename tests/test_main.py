"""Tests for theswarm.main — settings loading, KeywordNLU, connect helper."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── load_swarm_settings ──────────────────────────────────────────────


def test_load_swarm_settings_defaults(tmp_path):
    """Loads default settings from a minimal YAML file."""
    yaml_file = tmp_path / "theswarm.yaml"
    yaml_file.write_text("mattermost:\n  base_url: https://mm.test\n")

    with patch.dict(os.environ, {}, clear=True):
        from theswarm.main import load_swarm_settings
        settings = load_swarm_settings(str(yaml_file))

    assert settings.server.port == 8091
    assert settings.agents.swarm_po.enabled is False
    assert settings.agents.swarm_po.github_repos == []


def test_load_swarm_settings_env_mm_token(tmp_path):
    """SWARM_PO_MATTERMOST_TOKEN env var injects mm_token."""
    yaml_file = tmp_path / "theswarm.yaml"
    yaml_file.write_text("agents:\n  swarm_po:\n    enabled: true\n")

    with patch.dict(os.environ, {"SWARM_PO_MATTERMOST_TOKEN": "tok-abc"}, clear=True):
        from theswarm.main import load_swarm_settings
        settings = load_swarm_settings(str(yaml_file))

    assert settings.agents.swarm_po.mm_token == "tok-abc"


def test_load_swarm_settings_env_single_repo(tmp_path):
    """SWARM_PO_GITHUB_REPO sets both github_repos and default_repo."""
    yaml_file = tmp_path / "theswarm.yaml"
    yaml_file.write_text("{}")

    with patch.dict(os.environ, {"SWARM_PO_GITHUB_REPO": "owner/repo"}, clear=True):
        from theswarm.main import load_swarm_settings
        settings = load_swarm_settings(str(yaml_file))

    assert "owner/repo" in settings.agents.swarm_po.github_repos
    assert settings.agents.swarm_po.default_repo == "owner/repo"


def test_load_swarm_settings_env_repos_csv(tmp_path):
    """SWARM_PO_GITHUB_REPOS overrides with comma-separated list."""
    yaml_file = tmp_path / "theswarm.yaml"
    yaml_file.write_text("{}")

    with patch.dict(os.environ, {"SWARM_PO_GITHUB_REPOS": "a/b, c/d"}, clear=True):
        from theswarm.main import load_swarm_settings
        settings = load_swarm_settings(str(yaml_file))

    assert settings.agents.swarm_po.github_repos == ["a/b", "c/d"]


def test_load_swarm_settings_external_url_appends_swarm(tmp_path):
    """External URL gets /swarm suffix for Traefik routing."""
    yaml_file = tmp_path / "theswarm.yaml"
    yaml_file.write_text("server:\n  external_url: https://example.com\n")

    with patch.dict(os.environ, {}, clear=True):
        from theswarm.main import load_swarm_settings
        settings = load_swarm_settings(str(yaml_file))

    assert settings.server.external_url.endswith("/swarm")


def test_load_swarm_settings_external_url_already_has_swarm(tmp_path):
    """External URL already ending in /swarm is not doubled."""
    yaml_file = tmp_path / "theswarm.yaml"
    yaml_file.write_text("server:\n  external_url: https://example.com/swarm\n")

    with patch.dict(os.environ, {}, clear=True):
        from theswarm.main import load_swarm_settings
        settings = load_swarm_settings(str(yaml_file))

    assert settings.server.external_url == "https://example.com/swarm"


# ── _KeywordNLU ──────────────────────────────────────────────────────


@pytest.fixture()
def keyword_nlu():
    from theswarm.main import _KeywordNLU
    return _KeywordNLU()


async def test_keyword_nlu_help(keyword_nlu):
    intent = await keyword_nlu.parse_intent("help me", "swarm_po", [])
    assert intent.action == "help"


async def test_keyword_nlu_status(keyword_nlu):
    intent = await keyword_nlu.parse_intent("status", "swarm_po", [])
    assert intent.action == "show_status"


async def test_keyword_nlu_plan(keyword_nlu):
    intent = await keyword_nlu.parse_intent("plan du jour", "swarm_po", [])
    assert intent.action == "show_plan"


async def test_keyword_nlu_report(keyword_nlu):
    intent = await keyword_nlu.parse_intent("rapport", "swarm_po", [])
    assert intent.action == "show_report"


async def test_keyword_nlu_run_cycle(keyword_nlu):
    intent = await keyword_nlu.parse_intent("go", "swarm_po", [])
    assert intent.action == "run_cycle"


async def test_keyword_nlu_backlog(keyword_nlu):
    intent = await keyword_nlu.parse_intent("issues please", "swarm_po", [])
    assert intent.action == "list_stories"


async def test_keyword_nlu_repos(keyword_nlu):
    intent = await keyword_nlu.parse_intent("repos", "swarm_po", [])
    assert intent.action == "list_repos"


async def test_keyword_nlu_feature_description(keyword_nlu):
    intent = await keyword_nlu.parse_intent(
        "I want a dashboard that shows real-time cycle progress", "swarm_po", []
    )
    assert intent.action == "create_stories"
    assert intent.confidence < 0.8


async def test_keyword_nlu_unknown_short(keyword_nlu):
    intent = await keyword_nlu.parse_intent("xyz", "swarm_po", [])
    assert intent.action == "unknown"


# ── _connect_mattermost ──────────────────────────────────────────────


async def test_connect_mattermost_no_config():
    """Returns None when base_url or bot_token is empty."""
    from theswarm.main import _connect_mattermost
    from theswarm_common.config import MattermostConfig

    result = await _connect_mattermost(MattermostConfig(base_url="", bot_token=""))
    assert result is None


async def test_connect_mattermost_success():
    """Returns adapter on successful connection."""
    from theswarm.main import _connect_mattermost
    from theswarm_common.config import MattermostConfig

    config = MattermostConfig(base_url="https://mm.test", bot_token="tok")

    mock_adapter = AsyncMock()
    with patch("theswarm_common.chat.mattermost.MattermostAdapter", return_value=mock_adapter):
        result = await _connect_mattermost(config, label="test")

    assert result is mock_adapter
    mock_adapter.connect.assert_awaited_once()


async def test_connect_mattermost_failure():
    """Returns None when connection raises."""
    from theswarm.main import _connect_mattermost
    from theswarm_common.config import MattermostConfig

    config = MattermostConfig(base_url="https://mm.test", bot_token="tok")

    mock_adapter = AsyncMock()
    mock_adapter.connect.side_effect = ConnectionError("refused")
    with patch("theswarm_common.chat.mattermost.MattermostAdapter", return_value=mock_adapter):
        result = await _connect_mattermost(config, label="test")

    assert result is None


# ── SwarmSettings model ──────────────────────────────────────────────


def test_swarm_po_config_defaults():
    from theswarm.main import SwarmPoConfig
    cfg = SwarmPoConfig()
    assert cfg.enabled is False
    assert cfg.llm_backend == "claude-code"
    assert cfg.github_repos == []
    assert cfg.team_channel == "swarm-team"


def test_agents_config_defaults():
    from theswarm.main import AgentsConfig
    cfg = AgentsConfig()
    assert cfg.swarm_po.enabled is False
