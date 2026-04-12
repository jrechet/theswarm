"""Tests for theswarm_common/config.py — MattermostConfig, ServerConfig, load_yaml_with_env."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import yaml

from theswarm_common.config import (
    MattermostConfig,
    OllamaConfig,
    ServerConfig,
    load_yaml_with_env,
)


# ── MattermostConfig ─────────────────────────────────────────────────────


def test_mattermost_config_defaults():
    cfg = MattermostConfig()
    assert cfg.base_url == ""
    assert cfg.bot_token == ""
    assert cfg.channel_name == "swarm-bots-logs"


def test_mattermost_config_custom_values():
    cfg = MattermostConfig(
        base_url="https://mm.example.com",
        bot_token="tok123",
        channel_name="custom-channel",
    )
    assert cfg.base_url == "https://mm.example.com"
    assert cfg.bot_token == "tok123"
    assert cfg.channel_name == "custom-channel"


# ── OllamaConfig ────────────────────────────────────────────────────────


def test_ollama_config_defaults():
    cfg = OllamaConfig()
    assert cfg.base_url == "http://host.docker.internal:11434"
    assert cfg.model == "mistral:7b"
    assert cfg.timeout == 300


# ── ServerConfig ─────────────────────────────────────────────────────────


def test_server_config_defaults():
    cfg = ServerConfig()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8090
    assert cfg.external_url == ""


def test_server_config_valid_external_url():
    cfg = ServerConfig(external_url="https://swarm.example.com")
    assert cfg.external_url == "https://swarm.example.com"


def test_server_config_http_external_url():
    cfg = ServerConfig(external_url="http://localhost:8090")
    assert cfg.external_url == "http://localhost:8090"


def test_server_config_invalid_external_url():
    with pytest.raises(ValueError, match="external_url must start with http"):
        ServerConfig(external_url="ftp://bad.example.com")


def test_server_config_empty_external_url_is_valid():
    cfg = ServerConfig(external_url="")
    assert cfg.external_url == ""


# ── load_yaml_with_env ───────────────────────────────────────────────────


def test_load_yaml_with_env_reads_yaml_file(tmp_path):
    yaml_content = {
        "mattermost": {"base_url": "https://mm.test.com", "channel_name": "test-chan"},
        "server": {"port": 9000},
    }
    config_file = tmp_path / "theswarm.yaml"
    config_file.write_text(yaml.dump(yaml_content))

    with patch("dotenv.load_dotenv"):
        result = load_yaml_with_env(config_file)

    assert result["mattermost"]["base_url"] == "https://mm.test.com"
    assert result["mattermost"]["channel_name"] == "test-chan"
    assert result["server"]["port"] == 9000


def test_load_yaml_with_env_nonexistent_file(tmp_path):
    missing_file = tmp_path / "does_not_exist.yaml"

    with patch("dotenv.load_dotenv"):
        result = load_yaml_with_env(missing_file)

    assert result == {}


def test_load_yaml_with_env_injects_mattermost_bot_token(tmp_path):
    config_file = tmp_path / "theswarm.yaml"
    config_file.write_text(yaml.dump({"server": {"port": 8080}}))

    with patch("dotenv.load_dotenv"), \
         patch.dict(os.environ, {"MATTERMOST_BOT_TOKEN": "env-token-123"}, clear=False):
        result = load_yaml_with_env(config_file)

    assert result["mattermost"]["bot_token"] == "env-token-123"


def test_load_yaml_with_env_injects_ollama_base_url(tmp_path):
    config_file = tmp_path / "theswarm.yaml"
    config_file.write_text(yaml.dump({}))

    with patch("dotenv.load_dotenv"), \
         patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://localhost:11434"}, clear=False):
        result = load_yaml_with_env(config_file)

    assert result["ollama"]["base_url"] == "http://localhost:11434"


def test_load_yaml_with_env_injects_external_url(tmp_path):
    config_file = tmp_path / "theswarm.yaml"
    config_file.write_text(yaml.dump({}))

    with patch("dotenv.load_dotenv"), \
         patch.dict(os.environ, {"EXTERNAL_URL": "https://swarm.prod.com"}, clear=False):
        result = load_yaml_with_env(config_file)

    assert result["server"]["external_url"] == "https://swarm.prod.com"


def test_load_yaml_with_env_env_overrides_yaml(tmp_path):
    """Env vars override values already present in the YAML file."""
    yaml_content = {
        "mattermost": {"bot_token": "yaml-token"},
    }
    config_file = tmp_path / "theswarm.yaml"
    config_file.write_text(yaml.dump(yaml_content))

    with patch("dotenv.load_dotenv"), \
         patch.dict(os.environ, {"MATTERMOST_BOT_TOKEN": "env-token"}, clear=False):
        result = load_yaml_with_env(config_file)

    # Env var should override YAML value
    assert result["mattermost"]["bot_token"] == "env-token"


def test_load_yaml_with_env_empty_yaml(tmp_path):
    """An empty YAML file returns an empty dict (possibly with env injections)."""
    config_file = tmp_path / "theswarm.yaml"
    config_file.write_text("")

    # Clear env vars that would inject
    env_clear = {
        "MATTERMOST_BOT_TOKEN": "",
        "OLLAMA_BASE_URL": "",
        "EXTERNAL_URL": "",
    }
    with patch("dotenv.load_dotenv"), \
         patch.dict(os.environ, {}, clear=False):
        # Remove the env vars entirely
        for k in env_clear:
            os.environ.pop(k, None)
        result = load_yaml_with_env(config_file)

    assert result == {}


def test_load_yaml_with_env_multiple_env_vars(tmp_path):
    """Multiple env vars are all injected simultaneously."""
    config_file = tmp_path / "theswarm.yaml"
    config_file.write_text(yaml.dump({"server": {"host": "0.0.0.0"}}))

    env = {
        "MATTERMOST_BOT_TOKEN": "mm-tok",
        "OLLAMA_BASE_URL": "http://ollama:11434",
        "EXTERNAL_URL": "https://ext.example.com",
    }
    with patch("dotenv.load_dotenv"), \
         patch.dict(os.environ, env, clear=False):
        result = load_yaml_with_env(config_file)

    assert result["mattermost"]["bot_token"] == "mm-tok"
    assert result["ollama"]["base_url"] == "http://ollama:11434"
    assert result["server"]["external_url"] == "https://ext.example.com"
    # Original YAML values preserved
    assert result["server"]["host"] == "0.0.0.0"
